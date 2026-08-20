from sqlmodel import create_engine, Session
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # drops dead connections instead of erroring
    echo=settings.ENVIRONMENT == "development",
)


def get_session():
    with Session(engine) as session:
        yield session