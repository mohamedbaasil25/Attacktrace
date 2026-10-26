# Build context is the repository root (see docker-compose.yml), so this image can also include
# the attacker module: LIVE mode's POST /api/attack writes to the emulator through it.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/eval ./eval
COPY attacker ./attacker
# pip itself first (Phase 5.1: the base image's pip had several known CVEs, CVE-2026-13346 among
# them -- build-time only, since this image never installs from an untrusted index afterward, but
# cheap and safe to close). CPU-only torch keeps the image small.
RUN pip install --no-cache-dir --upgrade "pip>=26.1.2" \
 && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir .
COPY backend/models ./models
# Phase 5.1: run as a non-root user. /app/models, /data/live and /reports are the only paths the
# process writes to (bind-mounted by docker-compose.yml); /data/hai is mounted read-only already.
# The container still STARTS as root (the image default, unchanged below) so the entrypoint can
# `chown` whatever the bind mounts actually present at that moment -- including pre-existing
# files left over from this project's own earlier root-owned container runs, which a one-time
# build-time `chown` on the image's own baked-in copies cannot reach, since bind mounts replace
# that content at `docker run` time regardless. Confirmed necessary and sufficient by actually
# running `docker compose up` against this image (see the Phase 5.1 report).
RUN useradd --create-home --uid 1000 --user-group appuser \
 && chown -R appuser:appuser /app
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
