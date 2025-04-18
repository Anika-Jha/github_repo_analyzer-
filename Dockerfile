# Use Python 3.12 slim image as base
# Slim image is smaller but still includes required system libraries
FROM python:3.12-slim

# Set environment variables
# Prevents Python from writing pyc files to disc (reduces container size)
ENV PYTHONDONTWRITEBYTECODE=1
# Prevents Python from buffering stdout and stderr (ensures log messages are output immediately)
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
# Group commands to reduce number of layers and optimize cache
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file separately to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the project files into the container
# This is done after installing dependencies to leverage cache for faster builds
COPY . .

# Expose the port Streamlit will run on
EXPOSE 8501

# Set environment variables for Streamlit
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

# Create a non-root user for security
RUN useradd -m -r streamlit
RUN chown -R streamlit:streamlit /app
USER streamlit

# Command to run the application
# Use 0.0.0.0 to allow external connections
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
