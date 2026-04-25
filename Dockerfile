# Stage 1: Build dependencies using a SAM-like build image (includes gcc/development tools)
FROM public.ecr.aws/sam/build-python3.11 as builder

WORKDIR /build

# Copy project files
COPY pyproject.toml .
COPY README.md .

# Install dependencies into a specific directory
# We use --no-cache-dir to keep the layer small
RUN pip install --upgrade pip && \
  pip install ".[ml]" --target /build/package --no-cache-dir

# Stage 2: Final Runtime Image (Minimal AWS Lambda image)
FROM public.ecr.aws/lambda/python:3.11

WORKDIR ${LAMBDA_TASK_ROOT}

# Copy installed packages from builder
COPY --from=builder /build/package ${LAMBDA_TASK_ROOT}

# Copy application code
COPY app/ ${LAMBDA_TASK_ROOT}/app/
COPY data/ ${LAMBDA_TASK_ROOT}/data/

# Set environment variables
ENV PYTHONPATH=${LAMBDA_TASK_ROOT}
ENV APP_ENV=production
ENV LOG_LEVEL=INFO

# Command to run the Lambda handler
CMD [ "app.main.handler" ]
