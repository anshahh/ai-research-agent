# Security Gateway - Dockerfile
#
# Purpose: package the gateway as a container so it runs identically
# regardless of host machine, and so it can be deployed alongside the
# agent via docker-compose (or separately, to any container host).

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/app/data"]
ENV GATEWAY_DB_PATH=/app/data/gateway_decisions.db

EXPOSE 8010

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
