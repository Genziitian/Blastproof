# The Blast Radius UI and its agents, for a public read-only demo (docs/DEPLOY.md).
# FalkorDB runs beside it (docker-compose.public.yml) or on FalkorDB Cloud.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Demo timing (6 s lease) so a takeover is visible; public = read-only, self-playing.
ENV PYTHONUNBUFFERED=1 TIMING_PROFILE=demo PUBLIC_MODE=1 PORT=8000
EXPOSE 8000
# Investigators run as child processes, so a kill in the story is a real process exit.
CMD ["sh", "-c", "python -m web.app --company a --host 0.0.0.0 --port ${PORT}"]
