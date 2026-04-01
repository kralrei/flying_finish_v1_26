# Use Python 3.9 as base
FROM python:3.9-slim

# Install system dependencies (for psycopg2)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port (adjust if using another port than 5000)
EXPOSE 5000

# Start Flask app using Waitress or Gunicorn (Flask dev server not recommended)
CMD ["python", "app.py"]
