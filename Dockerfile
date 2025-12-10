FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create directories for downloads
RUN mkdir -p /app/gmaps_downloads

# Collect static files (doesn't need DB)
RUN python manage.py collectstatic --noinput --clear || true

# Expose port
EXPOSE 8000

# Run migrations at container START (not build), then start gunicorn
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn --config gunicorn-cfg.py config.wsgi"]
