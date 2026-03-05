from contextlib import contextmanager
from typing import Generator, Optional, Type, TypeVar

from sqlmodel import Session, SQLModel, create_engine, select

from models.movie import MovieTorrent
from models.movie import MovieTorrent
from models.show import ShowTorrent
from models.torrent import Torrent

T = TypeVar("T", bound=SQLModel)


# ---------------------------------------------------------------------------
# Engine & session management
# ---------------------------------------------------------------------------

def _create_engine(db_url: str):
    return create_engine(
        db_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )


_default_engine = _create_engine("sqlite:///database.db")


@contextmanager
def get_session(engine=None) -> Generator[Session, None, None]:
    """Context manager that provides a session and handles commit/rollback."""
    engine = engine or _default_engine
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


# ---------------------------------------------------------------------------
# Generic CRUD repository
# ---------------------------------------------------------------------------

class BaseRepository:
    """
    Generic repository that works with any SQLModel table class.

    Usage:
        repo = BaseRepository(Torrent)
        torrent = repo.get(1)
        torrents = repo.get_all()
        repo.save(torrent)
        repo.delete(torrent)
    """

    def __init__(self, model: Type[T], engine=None) -> None:
        self.model = model
        self.engine = engine or _default_engine
        SQLModel.metadata.create_all(self.engine)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, record_id: int) -> Optional[T]:
        with get_session(self.engine) as session:
            record = session.get(self.model, record_id)
            if record:
                session.expunge(record)
            return record

    def get_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        with get_session(self.engine) as session:
            statement = select(self.model).offset(offset).limit(limit)
            results = session.exec(statement).all()
            for r in results:
                session.expunge(r)
            return results

    def find_by(self, **kwargs) -> list[T]:
        """Find records matching all provided field=value filters."""
        with get_session(self.engine) as session:
            statement = select(self.model)
            for field, value in kwargs.items():
                statement = statement.where(getattr(self.model, field) == value)
            results = session.exec(statement).all()
            for r in results:
                session.expunge(r)
            return results

    def find_first_by(self, **kwargs) -> Optional[T]:
        """Return the first record matching all provided field=value filters."""
        with get_session(self.engine) as session:
            statement = select(self.model)
            for field, value in kwargs.items():
                statement = statement.where(getattr(self.model, field) == value)
            record = session.exec(statement).first()
            if record:
                session.expunge(record)
            return record

    def iter_chunks(self, chunk_size: int = 1000) -> Generator[T, None, None]:
        """Memory-safe iteration over large tables."""
        with Session(self.engine) as session:
            statement = select(self.model)
            for record in session.exec(statement).yield_per(chunk_size):
                yield record

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(self, record: T) -> T:
        """Insert or update a single record."""
        with get_session(self.engine) as session:
            record = session.merge(record)
            session.flush()
            session.refresh(record)
            session.expunge(record)
            return record

    def save_many(self, records: list[T]) -> None:
        """Bulk insert — efficient for large batches."""
        with get_session(self.engine) as session:
            session.add_all(records)

    def upsert_many(self, records: list[T]) -> None:
        """Insert or update records based on primary key."""
        with get_session(self.engine) as session:
            for record in records:
                existing = session.get(self.model, record.id)
                if existing:
                    for key, value in record.model_dump(exclude_unset=True).items():
                        setattr(existing, key, value)
                    session.add(existing)
                else:
                    session.add(record)
            print(f"Successfully synced {len(records)} records to database.")

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, record: T) -> None:
        with get_session(self.engine) as session:
            record = session.merge(record)
            session.delete(record)

    def delete_by_id(self, record_id: int) -> bool:
        with get_session(self.engine) as session:
            record = session.get(self.model, record_id)
            if record is None:
                return False
            session.delete(record)
            return True


# ---------------------------------------------------------------------------
# Domain-specific repositories
# ---------------------------------------------------------------------------

class TorrentRepository(BaseRepository):
    """Torrent-specific queries on top of the generic CRUD layer."""

    def __init__(self, engine=None) -> None:
        super().__init__(Torrent, engine)

class MovieRepository(BaseRepository):
    """Movie-specific queries on top of the generic CRUD layer."""

    def __init__(self, engine=None) -> None:
        super().__init__(MovieTorrent, engine)

class ShowRepository(BaseRepository):
    """Show-specific queries on top of the generic CRUD layer."""

    def __init__(self, engine=None) -> None:
        super().__init__(ShowTorrent, engine)