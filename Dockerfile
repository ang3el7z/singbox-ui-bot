FROM python:3.11-slim

WORKDIR /app

# System deps: curl for healthchecks, certbot for SSL, docker CLI for exec
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nginx \
    certbot \
    python3-certbot-nginx \
    docker.io \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY api/     ./api/
COPY bot/     ./bot/
COPY web/     ./web/
COPY nginx/   ./nginx/

# Create required directories
RUN mkdir -p /app/data /app/subs /app/nginx/conf.d /app/nginx/override /app/nginx/htpasswd

# Default port
EXPOSE 8080

CMD ["python", "-m", "bot.main"]
