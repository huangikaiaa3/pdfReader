"""Database session setup."""

from collections.abc import Generator

from pgvector.psycopg import register_vector
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


@event.listens_for(engine, "connect")
def connect(dbapi_connection, connection_record) -> None:
    """Register pgvector types with each Psycopg connection."""

    register_vector(dbapi_connection)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for request-scoped usage."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
