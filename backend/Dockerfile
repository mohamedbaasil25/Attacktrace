# Build context is the repository root (see docker-compose.yml), so this image can also include
# the attacker module: LIVE mode's POST /api/attack writes to the emulator through it.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/eval ./eval
COPY attacker ./attacker
# CPU-only torch keeps the image small.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir .
COPY backend/models ./models
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
