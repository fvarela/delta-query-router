FROM python:3.13-slim
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY server.py ./
COPY static/ ./static/
EXPOSE 8501
CMD [".venv/bin/uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8501"]
