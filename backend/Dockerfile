# Build context is the REPO ROOT (not backend/) so the image preserves the
# same backend/ nesting as local dev - pdf_export.py resolves REPORTS_DIR via
# Path(__file__).resolve().parents[3], which depends on that exact depth.
FROM python:3.12-slim

WORKDIR /workspace

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY run_backend.py run_backend.py

ENV PYTHONUNBUFFERED=1
# Cloud Run injects PORT and requires the container to listen on 0.0.0.0.
ENV HOST=0.0.0.0
EXPOSE 8080

CMD ["python", "run_backend.py"]
