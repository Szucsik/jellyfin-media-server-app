FROM python:3.12-slim

# Firefox + geckodriver for Selenium scraper
# RUN apt-get update && \
#     apt-get install -y --no-install-recommends firefox-esr wget && \
#     wget -q https://github.com/mozilla/geckodriver/releases/latest/download/geckodriver-v0.35.0-linux64.tar.gz -O /tmp/geckodriver.tar.gz && \
#     tar -xzf /tmp/geckodriver.tar.gz -C /usr/local/bin && \
#     rm /tmp/geckodriver.tar.gz && \
#     apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

EXPOSE 8800 8801

CMD ["python", "run.py"]
