from contextlib import contextmanager
from typing import Generator, Optional, Type, TypeVar

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy import exists, or_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from models.local_file_information import LocalFileInformation
from models.movie import Movie
from models.show import Show
from models.show_season import ShowSeason
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


def init_db(engine=None) -> None:
    """Create all tables. Call this ONCE from the main process before forking."""
    SQLModel.metadata.create_all(engine or _default_engine)

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
    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, record_id: int) -> Optional[T]:
        with get_session(self.engine) as session:
            record = session.get(self.model, record_id)
            if record:
                session.expunge(record)
            return record

    def get_all(self, offset: int = 0) -> list[T]:
        with get_session(self.engine) as session:
            statement = select(self.model).offset(offset)
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

    def save_new_only(self, records: list[Torrent]) -> None:
        """Insert only torrents whose torrent_id is not already in the database."""
        with get_session(self.engine) as session:
            existing_ids = set(
                session.exec(select(Torrent.torrent_id)).all()
            )
            new_records = [r for r in records if r.torrent_id not in existing_ids]
            if new_records:
                session.add_all(new_records)
                print(f"Inserted {len(new_records)} new torrents (skipped {len(records) - len(new_records)} duplicates).")
            else:
                print(f"No new torrents to insert (all {len(records)} already exist).")

    def find_by_imdb_id(self, imdb_id: str) -> Optional[Torrent]:
        """Find a torrent whose imdb_link contains the given IMDb ID (e.g. 'tt123456')."""
        with get_session(self.engine) as session:
            statement = select(self.model).where(
                self.model.imdb_link.contains(imdb_id)
            )
            record = session.exec(statement).first()
            if record:
                session.expunge(record)
            return record

    def find_registered_media_by_imdb_id(self, imdb_id: str) -> Optional[Torrent]:
        """Find a torrent whose imdb_link contains the given IMDb ID and is linked to a Movie or ShowSeason."""
        with get_session(self.engine) as session:
            statement = (
                select(self.model)
                .where(self.model.imdb_link.contains(imdb_id))
                .where(
                    or_(
                        exists().where(Movie.torrent_id == self.model.id),
                        exists().where(ShowSeason.torrent_id == self.model.id),
                    )
                )
            )
            record = session.exec(statement).first()
            if record:
                session.expunge(record)
            return record

    def find_all_registered_media_by_imdb_id(self, imdb_id: str) -> list[Torrent]:
        """Find all torrents for the given IMDb ID that are linked to a Movie or ShowSeason.

        A multi-season show has one torrent per season, all sharing the same IMDb ID,
        so callers must resolve which torrent holds the played episode.
        """
        with get_session(self.engine) as session:
            statement = (
                select(self.model)
                .where(self.model.imdb_link.contains(imdb_id))
                .where(
                    or_(
                        exists().where(Movie.torrent_id == self.model.id),
                        exists().where(ShowSeason.torrent_id == self.model.id),
                    )
                )
            )
            records = session.exec(statement).all()
            for record in records:
                session.expunge(record)
            return list(records)

class MovieRepository(BaseRepository):
    """Movie-specific queries on top of the generic CRUD layer."""

    def __init__(self, engine=None) -> None:
        super().__init__(Movie, engine)

    def delete_by_torrent_id(self, torrent_id: int) -> bool:
        """Delete the movie associated with the given torrent_id. Returns True if deleted, False if not found."""
        with get_session(self.engine) as session:
            statement = select(self.model).where(self.model.torrent_id == torrent_id)
            record = session.exec(statement).first()
            if record is None:
                return False
            session.delete(record)
            return True

class ShowSeasonsRepository(BaseRepository):
    """Show season-specific queries on top of the generic CRUD layer."""

    def __init__(self, engine=None) -> None:
        super().__init__(ShowSeason, engine)

    def get_all_seasons_for_show(self, show_id: int) -> list[ShowSeason]:
        with get_session(self.engine) as session:
            statement = select(self.model).where(self.model.show_id == show_id)
            results = session.exec(statement).all()
            for r in results:
                session.expunge(r)
            return results

    def delete_by_torrent_id(self, torrent_id: int) -> bool:
        """Delete the show season associated with the given torrent_id. Returns True if deleted, False if not found."""
        with get_session(self.engine) as session:
            statement = select(self.model).where(self.model.torrent_id == torrent_id)
            record = session.exec(statement).first()
            if record is None:
                return False
            session.delete(record)
            return True

class ShowRepository(BaseRepository):
    """Show-specific queries on top of the generic CRUD layer."""

    def __init__(self, engine=None) -> None:
        super().__init__(Show, engine)

class LocalFilesRepository(BaseRepository):

    def __init__(self, engine=None) -> None:
        super().__init__(LocalFileInformation, engine)

    def save_if_new(self, record: LocalFileInformation) -> None:
        """
        Insert the record only if its torrent_id is not already present.
        Silently does nothing on a duplicate torrent_id.
        """
        with get_session(self.engine) as session:
            stmt = (
                sqlite_insert(LocalFileInformation)
                .values(
                    torrent_id=record.torrent_id,
                    torrent_file_local_path=record.torrent_file_local_path,
                    main_media_files_local_path=record.main_media_files_local_path,
                    original_file_path=record.original_file_path,
                    symlink_path=record.symlink_path,
                )
                .on_conflict_do_nothing(index_elements=["torrent_id"])
            )
            session.exec(stmt)