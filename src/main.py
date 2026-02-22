import logging
import os

from ncore_scraper.scraper import Scraper


logging.basicConfig(
    filename='run.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

username = os.getenv("NCORE_USERNAME")
password = os.getenv("NCORE_PASSWORD")

if username is None or password is None:
    raise ValueError("NCORE_USERNAME or NCORE_PASSWORD is not set")

scraper = Scraper(username=username, password=password)

scraper.login()
scraper.get_all_hd_movies()