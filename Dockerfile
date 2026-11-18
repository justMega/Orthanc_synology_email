# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code. Secrets are NOT baked into the image: pass them with --env-file .env
COPY main.py message.txt ./
COPY templates/ ./templates

# Expose port
EXPOSE 5000

# Run the app
CMD ["python", "main.py"]
