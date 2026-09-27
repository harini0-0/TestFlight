FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir uv && uv sync --all-packages --no-dev
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "gateway.main:app", "--app-dir", "services/gateway/src", "--host", "0.0.0.0", "--port", "8000"]
