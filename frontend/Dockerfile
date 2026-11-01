# Step 1: Build static files
FROM node:24 AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Step 2: Serve static files and reverse proxy API via nginx
FROM nginx:1.29
WORKDIR /app

LABEL org.opencontainers.image.source="https://github.com/NHWS-Org/home-inventory" \
      org.opencontainers.image.description="Home Inventory frontend: React web app served by nginx for the shared household inventory app." \
      org.opencontainers.image.maintainer="napalmz"

# Install required tools
RUN apt-get update \
  && apt-get install -y --no-install-recommends bash curl gettext-base imagemagick librsvg2-bin fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*

# Copy built frontend files
COPY --from=build /app/dist /usr/share/nginx/html

# Icone originali: base per il ribbon d'ambiente applicato all'avvio
RUN mkdir -p /opt/icons-orig \
  && cd /usr/share/nginx/html \
  && cp icon.svg favicon-32.png icon-192.png icon-512.png apple-touch-icon.png icon-maskable-512.png /opt/icons-orig/

# Copy nginx config
COPY nginx.conf.template /etc/nginx/nginx.conf.template

# Copy and prepare entrypoint
COPY entrypoint.sh /entrypoint.sh
COPY apply-env-icons.sh /apply-env-icons.sh
RUN chmod +x /entrypoint.sh /apply-env-icons.sh

EXPOSE 80

ENV BACKEND_BASE_URL=http://localhost:8000

ENTRYPOINT ["/entrypoint.sh"]

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD curl -fs http://localhost || exit 1