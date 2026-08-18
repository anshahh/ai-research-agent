# AI Research Agent - Dockerfile
#
# Purpose: package the agent so it runs identically regardless of host
# machine. The agent is a CLI script, not a long-running server -- this
# image's default command runs one research task.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "-m", "src.agent"]
