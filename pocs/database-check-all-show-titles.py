from pathlib import Path
import re

from sqlmodel import Session, create_engine, select

from models.torrent import Torrent


# --------------------------------------------------
# Configuration
# --------------------------------------------------

DATABASE_PATH = "/home/szucsiki/Documents/Projects/jellyfin-media-server/databases/database-blue.db"
OUTPUT_FILE = "0_not_handled_shows.txt"
OUTPUT_SUPPORTED_FILE = "0_handled_shows.txt"

CHUNK_SIZE = 1000

EPISODE = r"(?<![A-Za-z])E\d{2}"

regex_only_one_season = rf"^(?!.*{EPISODE})(?=.*\bS\d{{2}}\b)(?!.*\bS\d{{2}}\b.*\bS\d{{2}}\b).*$"

regex_only_one_se_season = rf"^(?!.*{EPISODE})(?=.*\bSe\d{{2}}\b)(?!.*\bSe\d{{2}}\b.*\bSe\d{{2}}\b).*$"

regex_exactly_two_seasons = rf"^(?!.*{EPISODE})(?=(?:.*\bS\d{{2}}\b){{2}})(?!(?:.*\bS\d{{2}}\b){{3}}).*$"

regex_exclude_season_and_episode = rf"^(?=.*\bS(?:e)?\d{{2}})(?=.*{EPISODE}).*$"

# --------------------------------------------------
# Database
# --------------------------------------------------

engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)


# --------------------------------------------------
# Export show titles
# --------------------------------------------------

def export_show_titles() -> None:

    output_path = Path(OUTPUT_FILE)
    output_supported_path = Path(OUTPUT_SUPPORTED_FILE)

    total = 0

    print("Starting show title export...")

    with Session(engine) as session:

        statement = (
            select(Torrent.title)
            .where(Torrent.is_show.is_(True))
            .order_by(Torrent.title)
        )

        results = session.exec(statement).yield_per(CHUNK_SIZE)

        one_season_shows: list[str] = []
        one_se_season_shows: list[str] = []
        two_season_shows: list[str] = []

        episode_exceptions: list[str] = []
        random_exceptions: list[str] = []

        for title in results:
            if re.search(regex_exactly_two_seasons, title, re.IGNORECASE):
                two_season_shows.append(title)
                continue

            if re.search(regex_only_one_se_season, title, re.IGNORECASE):
                one_se_season_shows.append(title)
                continue

            if re.search(regex_only_one_season, title, re.IGNORECASE):
                one_season_shows.append(title)
                continue

            if re.search(regex_exclude_season_and_episode, title, re.IGNORECASE):
                episode_exceptions.append(title)
                continue

            random_exceptions.append(title)


        with output_supported_path.open(
            mode="w",
            encoding="utf-8",
        ) as file:
            file.write("One Season\n")
            file.write(f"{"-"*100}\n\n")
            for title in one_season_shows:
                if not title:
                    continue

                file.write(f"{title}\n")

            file.write("One Se Season\n")
            file.write(f"{"-"*100}\n\n")
            for title in one_se_season_shows:
                if not title:
                    continue

                file.write(f"{title}\n")

            file.write("Two Seasons\n")
            file.write(f"{"-"*100}\n\n")
            for title in two_season_shows:
                if not title:
                    continue

                file.write(f"{title}\n")

        with output_path.open(
            mode="w",
            encoding="utf-8",
        ) as file:
            # file.write("Episode exceptions\n")
            # file.write(f"{"-"*100}\n\n")
            # for title in episode_exceptions:
            #     if not title:
            #         continue

            #     file.write(f"{title}\n")

            file.write("Random exceptions\n")
            file.write(f"{"-"*100}\n\n")
            for title in random_exceptions:
                if not title:
                    continue

                file.write(f"{title}\n")

    print()
    print("Export completed!")
    print(f"Total show titles: {total:,}")
    print(f"Output file: {output_path.resolve()}")


# --------------------------------------------------
# Main
# --------------------------------------------------

if __name__ == "__main__":
    export_show_titles()