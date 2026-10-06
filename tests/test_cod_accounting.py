from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from tests.test_inventory_release import seed
from app.models.user import User
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentStatus, PaymentProvider
from app.models.admin_audit import AdminAuditLog
from app.api.v1.admin.cod import collect_cod_payment, get_pending_cod_orders
from app.api.v1.webhooks import process_tracking_event
from app.repositories.commerce import settled_sale


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    uid, oid, _ = seed(engine)
    with Session(engine) as s:
        yield s, s.get(Order, oid), s.get(User, uid)
    engine.dispose()


def deliver(s, order):
    process_tracking_event(s, {"awb": order.awb_code, "current_status": "DELIVERED"})


def test_delivery_keeps_cod_out_of_revenue_until_collection(db):
    s, order, user = db
    deliver(s, order)
    assert order.status == OrderStatus.DELIVERED and order.payment_status == "cod_pending"
    assert not s.exec(select(Order).where(settled_sale())).all()
    collect_cod_payment(order.id, s, user)
    assert s.exec(select(Order).where(settled_sale())).one().id == order.id
    payment = s.exec(select(Payment)).one()
    assert payment.provider == PaymentProvider.COD and payment.status == PaymentStatus.SUCCEEDED
    assert payment.amount == Decimal("200") and payment.paid_at is not None
    assert s.exec(select(AdminAuditLog)).one().action == "cod.collected"
    process_tracking_event(s, {"awb": order.awb_code, "current_status": "DELIVERED", "date": "later"})
    with pytest.raises(HTTPException) as exc:
        collect_cod_payment(order.id, s, user)
    assert exc.value.status_code == 400
    assert len(s.exec(select(Payment)).all()) == 1


@pytest.mark.parametrize("status", [OrderStatus.CONFIRMED, OrderStatus.SHIPPED, OrderStatus.CANCELLED, OrderStatus.RTO, OrderStatus.REFUNDED])
def test_collection_rejects_not_delivered_states(db, status):
    s, order, user = db
    order.status = status
    s.add(order)
    s.commit()
    with pytest.raises(HTTPException):
        collect_cod_payment(order.id, s, user)
    assert not s.exec(select(Payment)).all()
    if status in (OrderStatus.CANCELLED, OrderStatus.RTO, OrderStatus.REFUNDED):
        assert get_pending_cod_orders(s, user)["count"] == 0


def test_collection_and_audit_roll_back_together(db):
    s, order, user = db
    deliver(s, order)
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO admin_audit_log"):
            raise RuntimeError("audit unavailable")
    event.listen(s.bind, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError):
            collect_cod_payment(order.id, s, user)
    finally:
        event.remove(s.bind, "before_cursor_execute", fail)
    assert order.payment_status == "cod_pending"
    assert not s.exec(select(Payment)).all()


def test_cod_truth_migration_preserves_real_collection(db):
    s, order, user = db
    deliver(s, order)
    order.payment_status = "paid"
    s.add(order)
    s.commit()
    path = Path(__file__).resolve().parents[1] / "alembic/versions/t5b6c7d8e9f0_cod_collection_truth.py"
    spec = importlib.util.spec_from_file_location("cod_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with s.bind.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
    s.expire_all()
    assert order.payment_status == "cod_pending"
    collect_cod_payment(order.id, s, user)
    with s.bind.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
    s.expire_all()
    assert order.payment_status == "paid"


def test_postgres_concurrent_collection_records_cash_once(postgres_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    uid, oid, _ = seed(postgres_engine)
    with Session(postgres_engine) as s:
        order = s.get(Order, oid)
        order.status = OrderStatus.DELIVERED
        s.add(order)
        s.commit()
    barrier = Barrier(2)
    def collect():
        with Session(postgres_engine) as s:
            user = s.get(User, uid)
            stale = s.get(Order, oid)
            barrier.wait(timeout=10)
            try:
                collect_cod_payment(stale.id, s, user)
                return 200
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(collect) for _ in range(2)]
        assert sorted(call.result(timeout=15) for call in calls) == [200, 400]
    with Session(postgres_engine) as s:
        assert len(s.exec(select(Payment)).all()) == 1
