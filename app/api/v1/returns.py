"""Owned customer return requests and authenticated private evidence."""
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, SessionDep
from app.models.product_return import ReturnEvidence
from app.schemas.product_return import ReturnCreate, ReturnNote, ReturnTracking
from app.services import product_return as service
from app.services.return_evidence import decode_images, evidence_path

router = APIRouter(tags=["Product Returns"])


def mutation(session, call, *, admin=False, written=None):
    try:
        row = call()
        session.flush()
        result = service.read_request(session, row, admin=admin)
        session.commit()
        return result
    except Exception as exc:
        session.rollback()
        for path in written or []:
            path.unlink(missing_ok=True)
        if isinstance(exc, IntegrityError):
            raise HTTPException(409, "This return action conflicts with an existing request or shipment") from exc
        if isinstance(exc, OSError):
            raise HTTPException(503, "Return evidence storage is temporarily unavailable") from exc
        raise


def evidence_response(session, return_id, evidence_id):
    image = session.get(ReturnEvidence, evidence_id)
    if image is None or image.return_id != return_id:
        raise HTTPException(404, "Evidence not found")
    path = evidence_path(image.storage_key)
    if not path.is_file():
        raise HTTPException(404, "Evidence not found")
    return FileResponse(path, media_type="image/jpeg", filename="return-image.jpg",
                        content_disposition_type="inline",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/orders/{order_id}/return-eligibility")
def return_eligibility(order_id: UUID, session: SessionDep, current_user: CurrentUser):
    return service.eligibility(session, service.owned_order(session, order_id, current_user), current_user)


@router.post("/orders/{order_id}/returns", status_code=201)
async def create_return(order_id: UUID, session: SessionDep, current_user: CurrentUser,
                        data: str = Form(..., max_length=20000), files: list[UploadFile] = File(default=[])):
    service.owned_order(session, order_id, current_user)
    try:
        parsed = ReturnCreate.model_validate_json(data)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False))
    images = await decode_images(files)
    written = []
    return mutation(session, lambda: service.create_request(session, order_id, current_user, parsed, images, written), written=written)


@router.get("/returns")
def customer_returns(session: SessionDep, current_user: CurrentUser,
                     order_id: UUID | None = None, page: int = Query(default=1, ge=1),
                     limit: int = Query(default=20, ge=1, le=100)):
    return service.list_requests(session, owner=current_user, page=page, limit=limit, order_id=order_id)


@router.get("/returns/{return_id}")
def return_detail(return_id: UUID, session: SessionDep, current_user: CurrentUser):
    return service.read_request(session, service.get_request(session, return_id, owner=current_user))


@router.post("/returns/{return_id}/cancel")
def cancel_return(return_id: UUID, data: ReturnNote, session: SessionDep, current_user: CurrentUser):
    return mutation(session, lambda: service.cancel(session, return_id, current_user, data.note))


@router.post("/returns/{return_id}/tracking")
def attach_return_tracking(return_id: UUID, data: ReturnTracking, session: SessionDep, current_user: CurrentUser):
    return mutation(session, lambda: service.attach_tracking(session, return_id, current_user, data))


@router.post("/returns/{return_id}/evidence")
async def upload_evidence(return_id: UUID, session: SessionDep, current_user: CurrentUser,
                          files: list[UploadFile] = File(...)):
    service.get_request(session, return_id, owner=current_user)
    images = await decode_images(files)
    written = []
    return mutation(session, lambda: service.add_evidence(session, return_id, current_user, images, written), written=written)


@router.get("/returns/{return_id}/evidence/{evidence_id}")
def download_evidence(return_id: UUID, evidence_id: UUID, session: SessionDep, current_user: CurrentUser):
    service.get_request(session, return_id, owner=current_user)
    return evidence_response(session, return_id, evidence_id)
