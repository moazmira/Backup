FROM postgres:16

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/backup-venv \
    && /opt/backup-venv/bin/pip install -r requirements.txt

COPY . .

CMD ["/opt/backup-venv/bin/python", "main.py"]
