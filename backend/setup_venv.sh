#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
REQ_FILE="requirements.txt"

if [ ! -f "$REQ_FILE" ]; then
  echo "[setup] Errore: $SCRIPT_DIR/$REQ_FILE non trovato." >&2
  exit 1
fi

# 1. crea venv se mancante
if [ ! -d "$VENV_DIR" ]; then
  echo "[setup] Creo virtualenv in $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

# 2. attiva venv
source "$VENV_DIR/bin/activate"

# 3. aggiorna pip
python -m pip install --upgrade pip wheel setuptools

# 4. installa pacchetti
echo "[setup] Installo dipendenze da $REQ_FILE"
python -m pip install -r "$REQ_FILE"

echo "[setup] Ambiente pronto. Attivalo con:"
printf 'source %q\n' "$SCRIPT_DIR/$VENV_DIR/bin/activate"
