FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY packages/engine/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY packages/engine/src ./src

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# Run worker
CMD ["python", "-m", "workers.main"]
