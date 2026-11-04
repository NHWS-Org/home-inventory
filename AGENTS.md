# AGENTS.md

Istruzioni operative per agenti AI che lavorano in questo repository.

## Scopo del progetto

- App inventario domestico con backend FastAPI + SQLAlchemy e frontend React + Vite.
- Deployment principale via Docker Compose.
- Dettagli utente e avvio rapido: [README.md](README.md).

## Setup rapido (preferito)

- Ambiente completo (db + backend + frontend): `docker-compose up --build -d`
- Compose di sviluppo (build locali): `docker-compose -f docker-compose-dev.yml up`
- Definizione servizi e variabili:
  - [docker-compose.yml](docker-compose.yml)
  - [docker-compose-dev.yml](docker-compose-dev.yml)

## Comandi locali utili

- Backend:
  - Setup venv: `cd backend && ./setup_venv.sh`
  - Run API: `cd backend && source .venv/bin/activate && uvicorn main:app --reload`
  - Test principali: `cd backend && source .venv/bin/activate && pytest .test/test_metadata_backend.py`
  - Suite backend completa: `cd backend && source .venv/bin/activate && pytest` (discovery configurata in [backend/pytest.ini](backend/pytest.ini)).
- Frontend:
  - Install: `cd frontend && npm ci`
  - Dev: `cd frontend && npm run dev`
  - Build: `cd frontend && npm run build`
  - Lint: `cd frontend && npm run lint`

## Confini architetturali

- Backend entrypoint e bootstrap API: [backend/main.py](backend/main.py)
- Modelli ORM e audit mixin: [backend/models.py](backend/models.py)
- Schema metadata EAV canonico: [backend/metadata_model.py](backend/metadata_model.py)
- Router API modulari: [backend/routes](backend/routes)
- Scheduler backup/audit cleanup: [backend/scheduler.py](backend/scheduler.py)
- Frontend app shell e routing: [frontend/src/App.tsx](frontend/src/App.tsx)
- Client API frontend: [frontend/src/api.ts](frontend/src/api.ts)

## Convenzioni progetto (importanti)

- Tracciamento audit: i modelli usano il mixin `LoggingData` (campi user/data ins/mod).
- EAV metadata: rispettare tipi e operatori definiti in [backend/metadata_model.py](backend/metadata_model.py); evitare logica duplicata in altri file.
- Ruoli applicativi: admin/moderator/viewer nel dominio backend.
- Root path API dietro proxy: variabile `FASTAPI_ROOT_PATH=/api` nei compose.
- File di test: collocarli esclusivamente in [backend/.test/](backend/.test/) o [frontend/.test/](frontend/.test/), secondo il componente interessato; non crearli nella root del componente o insieme al codice applicativo. Quando si aggiungono o spostano test, mantenere coerenti discovery, import, percorsi e comandi di esecuzione.

## Pitfall ricorrenti

- In Docker il DB host è `db`; in locale spesso `localhost`. Verificare `DATABASE_URL` prima di test/migrazioni.
- L'entrypoint backend applica migrazioni all'avvio: [backend/entrypoint.sh](backend/entrypoint.sh).
- I test backend usano SQLite in-memory, non Postgres: [backend/.test/test_metadata_backend.py](backend/.test/test_metadata_backend.py).
- Il frontend dipende da `BACKEND_BASE_URL` (template nginx): [frontend/nginx.conf.template](frontend/nginx.conf.template).

## Strategia modifiche per agenti

- Cambiamenti backend:
  - Aggiornare insieme modello ORM, schema Pydantic e route/CRUD correlati.
  - Se cambia lo schema DB, aggiungere/aggiornare migrazione Alembic in [backend/migrations](backend/migrations).
- Cambiamenti frontend:
  - Tenere coerenti tipi, client API e pagine/componenti coinvolti.
- Validazione minima prima di chiudere il task:
  - Backend: test mirato o verifica endpoint interessato.
  - Frontend: `npm run lint` e build quando il cambiamento è ampio.

## Riferimenti da linkare invece di duplicare

- Guida deploy utente: [README.md](README.md)
- Dettagli stack frontend (template Vite): [frontend/README.md](frontend/README.md)