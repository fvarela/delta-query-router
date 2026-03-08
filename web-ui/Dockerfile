# Stage 1: Build React frontend
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# Output lands in /app/static/ (vite.config.ts: outDir '../static')

# Stage 2: Python runtime
FROM python:3.13-slim
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY server.py ./
COPY --from=frontend-build /app/static ./static/
EXPOSE 8501
CMD [".venv/bin/uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8501"]
