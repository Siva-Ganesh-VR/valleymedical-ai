# Single-service image: the FastAPI backend also serves the built React UI.
# Used for free-tier hosting (Render). Local development still uses docker-compose.yml.

FROM node:20-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VM_STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/fixtures ./fixtures
COPY --from=ui /ui/dist ./static
RUN useradd --create-home appuser && mkdir -p /app/data && chown appuser /app/data
USER appuser
EXPOSE 8000
# Render (and most hosts) pass the port in $PORT.
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
