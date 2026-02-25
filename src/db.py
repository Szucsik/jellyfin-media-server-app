from typing import Optional, List
from sqlmodel import Field, Session, SQLModel, create_engine, select, or_, col

from models import Torrent


class Database:
    """a"""

    sqlite_url = "sqlite:///database.db"
    engine = create_engine(sqlite_url)
    SQLModel.metadata.create_all(engine)

    def read(self):
        """a"""

        with Session(self.engine) as session:
            # 1. Get ALL movies
            statement = select(Torrent)
            results = session.exec(statement)
            all_movies = results.all() # Returns a list[Movie]

            # 2. Get ONE specific movie by ID
            movie = session.get(Torrent, 1) # Directly finds by primary key
            
            # 3. Get the FIRST match for a query
            statement = select(Torrent).where(Torrent.title == "Inception")
            inception = session.exec(statement).first()

    def update(self):
        """a"""

        with Session(self.engine) as session:
            # 1. Fetch
            statement = select(Torrent).where(Torrent.title == "Inception")
            movie = session.exec(statement).one()

            # 2. Modify
            movie.is_downloaded = True
            movie.title = "Inception (Updated)"

            # 3. Save
            session.add(movie) # Tells session to track this change
            session.commit()   # Writes to the .db file
            session.refresh(movie) # Optional: update object with DB state

    def write(self, movies: list[Torrent]):
        """a"""

        # Create the table if it doesn't exist
        SQLModel.metadata.create_all(self.engine)

        # --- NEW: Push to Database (with Upsert logic) ---
        with Session(self.engine) as session:
            for movie in movies:
                # Check if movie already exists to avoid Duplicate ID errors
                statement = select(Torrent).where(Torrent.id == movie.id)
                existing_movie = session.exec(statement).first()

                if existing_movie:
                    # Update existing record with new data from scraper
                    results = movie.model_dump(exclude_unset=True)
                    for key, value in results.items():
                        setattr(existing_movie, key, value)
                    session.add(existing_movie)
                else:
                    # Add as new record
                    session.add(movie)

            session.commit()
            print(f"Successfully synced {len(movies)} movies to SQLite.")
