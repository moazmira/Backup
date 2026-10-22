FROM postgres:18-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/backup-venv \
    && /opt/backup-venv/bin/pip install --no-cache-dir -r requirements.txt
COPY config config
COPY connections connections
COPY services services
COPY utils utils
COPY main.py .
ENV TZ=Africa/Cairo PG_DUMP_PATH=/usr/bin/pg_dump PYTHONUNBUFFERED=1
ENTRYPOINT ["/opt/backup-venv/bin/python", "main.py"]
