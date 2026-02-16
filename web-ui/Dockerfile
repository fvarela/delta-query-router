FROM python:3.13-slim
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
EXPOSE 8501
# Run the application
CMD [".venv/bin/streamlit", "run", "app.py", "--server.address", "0.0.0.0", "--server.port", "8501"]
