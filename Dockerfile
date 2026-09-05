FROM node:24-bookworm-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/ /app/backend/
RUN python -m pip install --no-cache-dir /app/backend

COPY data/ /app/data/
COPY --from=frontend-build /app/frontend/dist/ /app/frontend/dist/

WORKDIR /app/backend
EXPOSE 10000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
