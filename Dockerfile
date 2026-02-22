# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
COPY massage.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install python-dotenv  # for reading .env files

# Copy app code
COPY main.py .
COPY templates/ ./templates
COPY .env .

# Expose port
EXPOSE 5000

# Run the app
CMD ["python", "main.py"]