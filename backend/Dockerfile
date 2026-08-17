FROM python:3.12-slim

WORKDIR /opt/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# OpenShift runs containers with an arbitrary non-root UID (group 0);
# keep everything group-readable/writable and don't assume a fixed user.
# data/ holds the SQLite store (mount a PVC there, or set DATABASE_URL).
RUN mkdir -p /opt/app/data && chgrp -R 0 /opt/app && chmod -R g=u /opt/app
USER 1001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
