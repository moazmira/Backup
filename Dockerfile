FROM postgres:18

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/backup-venv \
    && /opt/backup-venv/bin/pip install --no-cache-dir -r requirements.txt

COPY backup.py .

CMD ["/opt/backup-venv/bin/python", "backup.py"]
