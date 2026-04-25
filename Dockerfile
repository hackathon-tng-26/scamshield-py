# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY README.md .

RUN pip install --upgrade pip && \
  pip install ".[ml]" --target /build/package --no-cache-dir --only-binary=numpy,scikit-learn,pandas,shap,psycopg2-binary,scipy

# Stage 2: Final Runtime Image
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages
COPY --from=builder /build/package /usr/local/lib/python3.11/site-packages/
# Also copy binaries like uvicorn
COPY --from=builder /build/package/bin/ /usr/local/bin/

# Copy application code
COPY app/ ./app/
COPY data/ ./data/
COPY scripts/ ./scripts/

# Set environment variables
ENV PYTHONPATH=/app
ENV APP_ENV=production
ENV LOG_LEVEL=INFO

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
