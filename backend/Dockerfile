# Usa un'immagine di base con Python
FROM python:3.14.4-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/NHWS-Org/home-inventory" \
      org.opencontainers.image.description="Home Inventory backend: FastAPI API for the shared household inventory app." \
      org.opencontainers.image.maintainer="napalmz"

# Imposta le variabili d'ambiente
ENV PYTHONDONTWRITEBYTECODE=1

# Aggiungi repository PostgreSQL in modo moderno e sicuro
RUN apt-get update && apt-get install -y wget gnupg lsb-release && \
    echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
    wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgres.gpg

# Install curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client-18 \
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

# Pulisci i file non necessari
RUN rm -f Dockerfile requirements.txt

# Esponi la porta 8000 per FastAPI
EXPOSE 8000

# Crea cartelle per i backup e imposta i permessi
RUN mkdir -p /app/backups && chmod 777 /app/backups

# Canale dell'immagine (release|dev), usato dalla telemetria opt-in
ARG IMAGE_CHANNEL=release
ENV IMAGE_CHANNEL=$IMAGE_CHANNEL

# Comando per avviare l'API
ENTRYPOINT ["/app/entrypoint.sh"]

HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD curl -fs http://localhost:8000/system/health-check || exit 1