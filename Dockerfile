# Use official Python lightweight image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy setup file and package directory
COPY setup.py .
COPY adeval/ adeval/

# Install the package
RUN pip install --no-cache-dir .

# Create directory for experiments and set as environment variable
RUN mkdir -p /app/data
ENV ADEVAL_DATA_DIR=/app/data

# Expose the default port
EXPOSE 8080

# Command to run the UI
# Data will be stored in $ADEVAL_DATA_DIR/.adeval
ENTRYPOINT ["adeval", "ui", "--host", "0.0.0.0", "--port", "8080"]