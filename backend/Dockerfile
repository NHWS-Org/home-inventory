# Usa un'immagine di base con Python
FROM python:3.14.4-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/NHWS-Org/home-inventory" \
      org.opencontainers.image.description="Home Inventory backend: FastAPI API for the shared household inventory app." \
      org.opencontainers.image.maintainer="napalmz"

# Imposta le variabili d'ambiente
ENV PYTHONDONTWRITEBYTECODE=1
ENV ALGORITHM=HS256 ACCESS_TOKEN_EXPIRE_MINUTES=14400

# Install curl
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Imposta la directory di lavoro nel container
WORKDIR /app

# Copia i file necessari
COPY requirements.txt .

# Aggiorna toolchain Python e installa dipendenze con versioni sicure
RUN pip install --no-cache-dir --upgrade "pip>=25.3" "wheel>=0.46.2" \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache

# Copia il codice dell'app
COPY . .

# Mantieni l'entrypoint fuori da /app, che puo essere coperta da un bind mount.
COPY entrypoint.sh /usr/local/bin/home-inventory-entrypoint
RUN chmod 755 /usr/local/bin/home-inventory-entrypoint

# Pulisci i file non necessari
RUN rm -f Dockerfile requirements.txt

# Esponi la porta 8000 per FastAPI
EXPOSE 8000

# Crea le cartelle dati e backup
RUN mkdir -p /app/data/backups && chmod 777 /app/data /app/data/backups

# Canale dell'immagine (release|dev), usato dalla telemetria opt-in
ARG IMAGE_CHANNEL=release
ENV IMAGE_CHANNEL=$IMAGE_CHANNEL

# Comando per avviare l'API
ENTRYPOINT ["/usr/local/bin/home-inventory-entrypoint"]

HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD curl -fsS -o /dev/null http://localhost:8000/system/health-check || exit 1