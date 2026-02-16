FROM python:3.11-slim
# Install uv
RUN pip install uv
# Set working directory
WORKDIR /app
# Copy dependency files
COPY pyproject.toml uv.lock .
# Install dependencies
RUN uv sync --frozen
# Copy application code
COPY . .
# Expose port
EXPOSE 8000
# Run the application
CMD [".venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]