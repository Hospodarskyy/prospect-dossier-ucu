# Prospect Dossier service, for a local run in Docker.
# Build from the project root (the agent package and requirements.txt live there):
#   docker build -f service/Dockerfile -t prospect-dossier .
# Run (configuration from the agent .env, data/ on the host keeps memory and results):
#   docker run --rm -p 8080:8080 --env-file dossier_agent/.env \
#     -v "$PWD/data:/app/data" --user "$(id -u):$(id -g)" prospect-dossier
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOME=/tmp

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY dossier_agent /app/dossier_agent
COPY service /app/service

# no secrets in the image: they come from --env-file at run time.
# data/ (storage, page cache) is mounted from the host; the image only needs the folder.
RUN mkdir -p /app/data
EXPOSE 8080

CMD ["sh", "-c", "uvicorn service.main:app --host 0.0.0.0 --port ${PORT}"]
