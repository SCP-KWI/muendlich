from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# sqlite needs check_same_thread=False when used across FastAPI's threadpool.
connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

def enable_sqlite_foreign_keys(target) -> None:
    """Make sqlite behave like Postgres about ON DELETE.

    sqlite ships with foreign keys *off*, so ON DELETE CASCADE silently does
    nothing: deleting a row leaves orphans instead of cleaning up after itself.
    Without this, dev and the test suite are a weaker check than production —
    the wrong way round. The test suite builds its own engine, so this is a
    function rather than an inline listener.
    """

    @event.listens_for(target, "connect")
    def _set_pragma(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


engine = create_engine(settings.database_url, connect_args=connect_args, future=True)

if settings.database_url.startswith("sqlite"):
    enable_sqlite_foreign_keys(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
