# Use official Python lightweight image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies if needed (e.g., for requests or other libs)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy setup file and package directory
COPY setup.py .
COPY adeval/ adeval/

# Install the package
RUN pip install --no-cache-dir .

# Create directory for experiments
RUN mkdir -p /app/data

# Set environment variable for the data storage location if needed 
# (Currently adeval uses os.getcwd(), so we run from /app/data)
WORKDIR /app/data

# Expose the default port
EXPOSE 8080

# Command to run the UI
# We use --host 0.0.0.0 to allow external connections
ENTRYPOINT ["adeval", "ui", "--host", "0.0.0.0", "--port", "8080"]
