# Build context is the REPO ROOT (kept consistent with backend/Dockerfile,
# though this one only needs frontend/).
FROM python:3.12-slim

WORKDIR /workspace/frontend

COPY frontend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY frontend/ .

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# BACKEND_URL is set at deploy time (Cloud Run --set-env-vars) to the backend
# service's own URL - api_client.py already reads it via os.environ.
CMD ["sh", "-c", "streamlit run Home.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true"]
