# Dashboard - Dockerfile
#
# Purpose: package the read-only dashboard as its own container. It
# needs network access to the agent's Postgres database and filesystem
# access to the gateway's decision log (via a shared volume in
# docker-compose), but never talks to the agent or gateway containers
# directly -- it only ever reads, never triggers actions.

FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn psycopg2-binary python-dotenv

COPY dashboard/ dashboard/

EXPOSE 8020

CMD ["uvicorn", "dashboard.main:app", "--host", "0.0.0.0", "--port", "8020"]
