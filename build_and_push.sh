#!/bin/bash

set -euo pipefail  # Interrompe l'esecuzione in caso di errore

usage() {
  echo "Uso: $0 [release|dev]"
  echo "  release (default): pubblica su Docker Hub e GHCR con latest e numero versione"
  echo "  dev:               pubblica su Docker Hub e GHCR con dev e numero-versione-dev"
}

CHANNEL="${1:-release}"
if [[ "$CHANNEL" != "release" && "$CHANNEL" != "dev" ]]; then
  usage
  exit 1
fi

# Ottiene le versioni per backend e frontend
BACKEND_VERSION=$(grep '^API_VERSION=' backend/.env | cut -d '=' -f2)
FRONTEND_VERSION=$(jq -r '.version' frontend/package.json)

if [[ -z "$BACKEND_VERSION" || "$BACKEND_VERSION" == "null" ]]; then
  echo "Errore: impossibile ottenere la versione del Backend."
  exit 1
fi
if [[ -z "$FRONTEND_VERSION" || "$FRONTEND_VERSION" == "null" ]]; then
  echo "Errore: impossibile ottenere la versione del Frontend."
  exit 1
fi

echo "Ultima versione di Backend: $BACKEND_VERSION"
echo "Ultima versione di Frontend: $FRONTEND_VERSION"
echo "Canale build selezionato: $CHANNEL"

# Esportiamo la versione come variabile globale per essere usata nei Dockerfile
export BACKEND_VERSION=$BACKEND_VERSION
export FRONTEND_VERSION=$FRONTEND_VERSION

PLATFORMS="linux/amd64,linux/arm64"

# Variabili per i tag
BACKEND_TAG_BASE="napalmzrpi/home-inventory-backend"
FRONTEND_TAG_BASE="napalmzrpi/home-inventory-frontend"
BACKEND_GHCR_TAG_BASE="ghcr.io/nhws-org/home-inventory-backend"
FRONTEND_GHCR_TAG_BASE="ghcr.io/nhws-org/home-inventory-frontend"

if [[ "$CHANNEL" == "release" ]]; then
  BACKEND_TAG_VERSION="$BACKEND_TAG_BASE:$BACKEND_VERSION"
  BACKEND_TAG_CHANNEL="$BACKEND_TAG_BASE:latest"
  BACKEND_GHCR_TAG_VERSION="$BACKEND_GHCR_TAG_BASE:$BACKEND_VERSION"
  BACKEND_GHCR_TAG_CHANNEL="$BACKEND_GHCR_TAG_BASE:latest"
  FRONTEND_TAG_VERSION="$FRONTEND_TAG_BASE:$FRONTEND_VERSION"
  FRONTEND_TAG_CHANNEL="$FRONTEND_TAG_BASE:latest"
  FRONTEND_GHCR_TAG_VERSION="$FRONTEND_GHCR_TAG_BASE:$FRONTEND_VERSION"
  FRONTEND_GHCR_TAG_CHANNEL="$FRONTEND_GHCR_TAG_BASE:latest"
else
  BACKEND_TAG_VERSION="$BACKEND_TAG_BASE:${BACKEND_VERSION}-dev"
  BACKEND_TAG_CHANNEL="$BACKEND_TAG_BASE:dev"
  BACKEND_GHCR_TAG_VERSION="$BACKEND_GHCR_TAG_BASE:${BACKEND_VERSION}-dev"
  BACKEND_GHCR_TAG_CHANNEL="$BACKEND_GHCR_TAG_BASE:dev"
  FRONTEND_TAG_VERSION="$FRONTEND_TAG_BASE:${FRONTEND_VERSION}-dev"
  FRONTEND_TAG_CHANNEL="$FRONTEND_TAG_BASE:dev"
  FRONTEND_GHCR_TAG_VERSION="$FRONTEND_GHCR_TAG_BASE:${FRONTEND_VERSION}-dev"
  FRONTEND_GHCR_TAG_CHANNEL="$FRONTEND_GHCR_TAG_BASE:dev"
fi

echo "Tag backend:"
printf '  - %s\n' "$BACKEND_TAG_VERSION" "$BACKEND_TAG_CHANNEL" "$BACKEND_GHCR_TAG_VERSION" "$BACKEND_GHCR_TAG_CHANNEL"
echo "Tag frontend:"
printf '  - %s\n' "$FRONTEND_TAG_VERSION" "$FRONTEND_TAG_CHANNEL" "$FRONTEND_GHCR_TAG_VERSION" "$FRONTEND_GHCR_TAG_CHANNEL"

# Funzione per chiedere conferma
ask_confirmation() {
  local prompt="$1 [Y/N] (default: N): "
  local response
  read -r -p "$prompt" response
  response=$(echo "$response" | tr '[:upper:]' '[:lower:]')  # Convertire in minuscolo

  if [[ "$response" == "y" ]]; then
    return 0  # Vero, esegui l'operazione
  else
    return 1  # Falso, salta l'operazione
  fi
}

# Chiedere se costruire l'immagine per Backend
if ask_confirmation "Vuoi costruire l'immagine per Backend?"; then
  echo "Costruzione dell'immagine per Backend..."
  cd backend || { echo "Directory backend non trovata"; exit 1; }
  docker buildx build --platform $PLATFORMS --build-arg BACKEND_VERSION=$BACKEND_VERSION --build-arg IMAGE_CHANNEL=$CHANNEL \
    -t $BACKEND_TAG_VERSION \
    -t $BACKEND_TAG_CHANNEL \
    -t $BACKEND_GHCR_TAG_VERSION \
    -t $BACKEND_GHCR_TAG_CHANNEL \
    -f Dockerfile . --push
  BUILD_SERVER=true
  cd ../ || { echo "Directory principale non trovata"; exit 1; }
else
  echo "Costruzione dell'immagine per Backend saltato."
fi

# Chiedere se costruire l'immagine per Frontend
if ask_confirmation "Vuoi costruire l'immagine per Frontend?"; then
  echo "Costruzione dell'immagine per Frontend..."
  cd frontend || { echo "Directory frontend non trovata"; exit 1; }
  docker buildx build --platform $PLATFORMS --build-arg FRONTEND_VERSION=$FRONTEND_VERSION \
    -t $FRONTEND_TAG_VERSION \
    -t $FRONTEND_TAG_CHANNEL \
    -t $FRONTEND_GHCR_TAG_VERSION \
    -t $FRONTEND_GHCR_TAG_CHANNEL \
    -f Dockerfile . --push
  BUILD_AGENT=true
  cd ../ || { echo "Directory principale non trovata"; exit 1; }
else
  echo "Costruzione dell'immagine per Frontend saltato."
fi
