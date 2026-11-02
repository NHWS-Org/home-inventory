# Home Inventory App

[🇮🇹 Italiano](#-italiano) · [🇬🇧 English](#-english)

![Active installations](https://img.shields.io/endpoint?url=https://home-inventory-telemetry.nhws.workers.dev/badge/installations)
![Countries](https://img.shields.io/endpoint?url=https://home-inventory-telemetry.nhws.workers.dev/badge/countries)
![Most used version](https://img.shields.io/endpoint?url=https://home-inventory-telemetry.nhws.workers.dev/badge/version)

---

## 🇮🇹 Italiano

Ho creato questa app per tenere un inventario condiviso degli oggetti di casa, ad esempio del contenuto del congelatore in garage o del mobile dei detersivi.

### Avvio

Per avviare il progetto con Docker, clona questo repository ed esegui:

```bash
docker-compose up --build -d
```

- API backend: <http://localhost:3000/api>
- Frontend: <http://localhost:3000>
- Credenziali predefinite: `admin` / `12345`

### Database e backup

Per impostazione predefinita l'app usa SQLite, senza un container database: il file e i backup compressi `.hibackup` sono conservati in `data/` (sul volume montato). I backup includono i metadati Alembic e possono essere ripristinati su un motore diverso. I vecchi backup PostgreSQL v2 vengono convertiti durante il caricamento della coppia `.sql` + `.sql.meta.json`.

Il volume persistente va montato su `/app/data`, non sull'intera directory `/app`: il codice e i file runtime dell'immagine devono restare visibili. L'entrypoint è installato in `/usr/local/bin` così non viene nascosto da bind mount dell'applicazione.

All'avvio il backend mostra il tipo di database e l'URL di destinazione con password mascherata e parametri query esclusi.

Il prefisso proxy `FASTAPI_ROOT_PATH` viene passato a Uvicorn dall'entrypoint Docker. Per un avvio locale dietro proxy usa `uvicorn main:app --reload --root-path /api`; senza proxy ometti `--root-path`.

Gli healthcheck Docker mantengono gli intervalli di controllo esistenti, ma non conservano il corpo delle risposte riuscite. Il frontend usa `/health-check`, verificando che `index.html` sia disponibile; il backend mantiene `/system/health-check` (controllo del processo API, non della connessione DB). I controlli riusciti non producono access log; gli errori e le normali richieste restano visibili. Per applicare queste modifiche occorre ricostruire o aggiornare entrambe le immagini e ricreare i container.

Se nei log compare `ModuleNotFoundError: No module named 'database'`, verifica che lo stack non monti una cartella dati su `/app`. Ad esempio, sostituisci `.../home-inventory-dev:/app` con `.../home-inventory-dev:/app/data` e ricrea il container. Se i backup erano nella sottocartella `backups`, il nuovo mount li espone direttamente in `/app/data/backups`. Non occorre modificare il volume PostgreSQL.

Per lo sviluppo locale, `./backend/setup_venv.sh` prepara `backend/.venv` usando il solo `backend/requirements.txt`, indipendentemente dalla directory da cui viene lanciato. Questo script non viene usato nel container Docker.

Per mantenere o scegliere PostgreSQL, imposta le due variabili e abilita il profilo corrispondente:

```bash
DATABASE_TYPE=POSTGRES DATABASE_URL='postgresql+psycopg://admin:admin@postgres:5432/inventory' docker compose --profile postgres up -d
```

Per MySQL o MariaDB usa il profilo `mysql` e un URL PyMySQL:

```bash
DATABASE_TYPE=MYSQL DATABASE_URL='mysql+pymysql://admin:admin@mysql:3306/inventory' docker compose --profile mysql up -d
```

`MYSQL` funziona sia con MySQL sia con MariaDB (`MARIADB` è accettato come alias). Sostituisci le credenziali d'esempio con credenziali sicure.

Per alimentare una nuova installazione (ad esempio DEV) con i dati di una vecchia:

1. Crea un backup dalla vecchia installazione e recupera entrambi i file: `nome.sql` e `nome.sql.meta.json`.
2. Nella pagina **Backup** della nuova installazione seleziona il file `.sql` e, nel campo che appare, il relativo `.sql.meta.json`.
3. Premi **Carica Backup**: il sistema converte gli INSERT del vecchio formato v2 in un archivio `.hibackup` compresso, con metadati incorporati. Nessun comando SQL del dump viene eseguito e il caricamento non modifica il database.
4. Crea un backup dei dati di destinazione e conferma separatamente il ripristino del file convertito. Scegli il ripristino avanzato con utenti/ruoli e admin per copiare anche gli accessi; lascia le impostazioni escluse per conservare la configurazione DEV.

La conversione accetta dump data-only generati dalla vecchia applicazione con `--column-inserts`, non dump PostgreSQL arbitrari (ad esempio `COPY`). File non corrispondenti, istruzioni/tabelle/colonne non supportate e revisioni Alembic discordanti vengono rifiutati esplicitamente; il restore mantiene i controlli di compatibilità con la revisione di destinazione. Conserva una copia della sorgente fino alla verifica dei dati migrati. Non serve un tool separato né una connessione dalla nuova installazione al database di produzione.

### Barcode e QR code

- Ogni articolo può avere più codici (EAN/UPC/QR e altri), gestibili dalla schermata di modifica.
- Il pulsante "Scansiona", nelle pagine inventario e checklist, consente di usare la fotocamera (desktop o mobile), un lettore USB/Bluetooth (che funziona come una tastiera) oppure l'inserimento manuale. La fotocamera richiede HTTPS (o localhost).
- Un codice sconosciuto consente di creare un nuovo articolo o associarlo a uno esistente. Ogni codice è univoco all'interno del proprio inventario.
- Ricerca dei dati EAN tramite Open Food Facts, Open Beauty Facts, Open Pet Food Facts e Open Products Facts, e dei libri (ISBN-10/ISBN-13, normalizzati a ISBN-13) tramite Open Library con fallback su Google Books (imposta `GOOGLE_BOOKS_API_KEY` per evitare i limiti di quota senza chiave): gratuita e senza chiave API, con cache locale. I farmaci sono riconosciuti (EAN, codice AIC a 9 cifre, GTIN estratto dal DataMatrix GS1) ma non esiste un'API pubblica per codice: l'anagrafica arriva solo se presente nelle fonti sopra. Si può disattivare impostando `BARCODE_LOOKUP_ENABLED=false`. Quando è attiva, i codici vengono inviati ai servizi esterni.

### Assegnazioni lista → inventario

- Dalla schermata di un articolo ("📋 Assegna") o da una lista ("📥 Da inventario") è possibile collegare una riga della lista a un articolo dell'inventario e indicare la quantità da prelevare.
- Spuntando la riga, la quantità assegnata viene sottratta dalla giacenza. Se la giacenza non è sufficiente, puoi scegliere se azzerarla o annullare l'operazione.
- Se deselezioni la riga entro 45 secondi, la giacenza viene ripristinata. Dopo 45 secondi, la giacenza non cambia e l'assegnazione torna attiva (utile per gli acquisti ricorrenti). Se riselezioni la riga entro 45 secondi dalla deselezione tardiva, l'operazione viene annullata senza sottrarre nuovamente la giacenza.
- Negli inventari, ogni riga mostra la giacenza lorda e quella netta (giacenza lorda meno le assegnazioni non ancora spuntate).

### Telemetria anonima (opt-in)

La telemetria è **disattivata di default**: non viene inviato nulla finché non la attivi esplicitamente. Serve a stimare quante installazioni sono attive e con quali versioni.

Per attivarla, imposta questa variabile d'ambiente del backend:

```yaml
TELEMETRY_ENABLED: "true"
```

I dati vengono inviati all'endpoint pubblico indicato in `DEFAULT_TELEMETRY_URL` in [telemetry_service.py](backend/telemetry_service.py). Chi ospita un proprio endpoint può sostituirlo con la variabile facoltativa `TELEMETRY_URL`.

Per disattivarla, rimuovi `TELEMETRY_ENABLED` o impostala a `false`, poi riavvia il backend.

Una volta al giorno (e poco dopo l'avvio) il backend invia un solo messaggio con:

| Dato | Descrizione |
|---|---|
| `id` | Identificativo casuale (UUID) generato in locale al primo invio, non collegato a utenti o macchine |
| `version` | Versione del backend |
| `inventories` | Numero di inventari (le checklist non contano) |
| `channel` | Canale dell'immagine: `release`, `dev` o `unknown` (build locale) |
| `last_activity` | Data dell'ultima modifica a inventari o articoli |

La **nazione** non viene inviata dal backend: la ricava il server di ricezione (Cloudflare) dalla richiesta, e l'indirizzo IP non viene salvato. Non vengono mai inviati nomi di inventari o articoli, utenti, password o altri contenuti. Se il server non è raggiungibile, l'invio fallisce in silenzio senza influire sull'app.

Il codice dell'endpoint di raccolta (Cloudflare Worker + D1) è in [telemetry-worker/](telemetry-worker/).

La tab **About** nella barra laterale mostra le versioni dell'app e le statistiche aggregate della community (installazioni attive negli ultimi 30 giorni, nazioni, versioni e canali release/dev in uso), lette dall'endpoint pubblico `/public-stats`. Si tratta di una semplice richiesta GET fatta dal backend, che non invia alcun dato dell'installazione e funziona anche con la telemetria disattivata. Per disattivare anche questa lettura imposta `ABOUT_STATS_ENABLED=false`.

### Pubblicazione immagini Docker

Le immagini multi-architettura (amd64 e arm64) vengono pubblicate sia su Docker Hub sia su GitHub Container Registry (GHCR).

#### Con GitHub Actions (consigliato)

Il workflow [publish-images.yml](.github/workflows/publish-images.yml) pubblica le immagini in questi casi:

| Evento | Tag pubblicati |
|---|---|
| Push su `main` (solo se cambiano `backend/`, `frontend/` o il workflow; i file `.md` sono ignorati) | `latest` e `<versione>` |
| Avvio manuale con canale `dev` (**Actions → Publish Docker images → Run workflow**, da qualsiasi branch) | `dev` e `<versione>-dev` |
| Avvio manuale con canale `release` | `latest` e `<versione>` |

Le versioni sono lette da `API_VERSION` in `backend/.env` e da `version` in `frontend/package.json`.

Configurazione necessaria:

- Secret del repository `DOCKERHUB_USERNAME` e `DOCKERHUB_TOKEN`.
- Per GHCR non serve alcun secret: il workflow usa il `GITHUB_TOKEN` con permesso `packages: write`. Ogni package GHCR deve concedere accesso **Write** al repository: in **Package settings → Manage Actions access** aggiungi `napalmz/home-inventory`.

#### Con lo script locale

Accedi a entrambi i registry:

```bash
docker login
docker login ghcr.io -u napalmz
```

Per GHCR usa un Personal Access Token (classic) di GitHub con permesso `write:packages` al posto della password. Poi esegui `./build_and_push.sh` per la release (tag `latest` e versione) oppure `./build_and_push.sh dev` per il canale di sviluppo (tag `dev` e versione `-dev`). Lo script chiede separatamente se costruire e pubblicare il backend e il frontend.

#### Collegamento al repository e visibilità

Entrambe le immagini includono la label OCI `org.opencontainers.image.source` con l'URL di questo repository. Per i package GHCR già creati, verifica o imposta il collegamento manualmente: nel profilo GitHub apri **Packages**, seleziona ciascun package (`home-inventory-backend` e `home-inventory-frontend`), fai clic su **Connect repository** e scegli `napalmz/home-inventory`.

Per rendere pubbliche le immagini, apri le **Package settings** di ciascun package e modifica la visibilità in **Public**. Il collegamento al repository e la visibilità sono impostazioni separate.

### Autori

- [@napalmz](https://www.github.com/napalmz)

---

## 🇬🇧 English

I built this app to keep a shared inventory of household items, such as the contents of a garage freezer or a cupboard with cleaning supplies.

### Getting started

To run this project with Docker, clone this repository and run:

```bash
docker-compose up --build -d
```

- Backend API: <http://localhost:3000/api>
- Frontend: <http://localhost:3000>
- Default credentials: `admin` / `12345`

### Database and backups

The app uses SQLite by default, with no database container: the database file and compressed `.hibackup` backups are stored in the mounted `data/` volume. Backups include Alembic metadata and can be restored to a different engine. Legacy v2 PostgreSQL backups are converted when uploading the `.sql` + `.sql.meta.json` pair.

Mount persistent storage at `/app/data`, not over the entire `/app` directory: the image's application code and runtime files must remain visible. The entrypoint is installed in `/usr/local/bin` so application bind mounts cannot hide it.

At startup, the backend logs the database type and destination URL with the password masked and query parameters omitted.

The Docker entrypoint passes the `FASTAPI_ROOT_PATH` proxy prefix to Uvicorn. For local startup behind a proxy, use `uvicorn main:app --reload --root-path /api`; without a proxy, omit `--root-path`.

Docker healthchecks keep their existing intervals but discard successful response bodies. The frontend uses `/health-check`, checking that `index.html` is available; the backend keeps `/system/health-check` (API process liveness, not database connectivity). Successful probes do not produce access logs; errors and normal requests remain visible. Rebuild or update both images and recreate the containers to apply these changes.

If logs show `ModuleNotFoundError: No module named 'database'`, check that the stack does not mount a data directory over `/app`. For example, replace `.../home-inventory-dev:/app` with `.../home-inventory-dev:/app/data` and recreate the container. Existing backups in the `backups` subdirectory will then be available at `/app/data/backups`. Leave the PostgreSQL volume unchanged.

For local development, `./backend/setup_venv.sh` prepares `backend/.venv` using only `backend/requirements.txt`, regardless of the directory it is launched from. Docker containers do not use this script.

To keep or select PostgreSQL, set both variables and enable its Compose profile:

```bash
DATABASE_TYPE=POSTGRES DATABASE_URL='postgresql+psycopg://admin:admin@postgres:5432/inventory' docker compose --profile postgres up -d
```

For MySQL or MariaDB, use the `mysql` profile and a PyMySQL URL:

```bash
DATABASE_TYPE=MYSQL DATABASE_URL='mysql+pymysql://admin:admin@mysql:3306/inventory' docker compose --profile mysql up -d
```

`MYSQL` works with both MySQL and MariaDB (`MARIADB` is accepted as an alias). Replace the example credentials with secure credentials.

To populate a new installation (for example DEV) from an older one:

1. Create a backup in the old installation and obtain both files: `name.sql` and `name.sql.meta.json`.
2. On the new installation's **Backup** page, select the `.sql` file and its matching `.sql.meta.json` in the additional field.
3. Click **Carica Backup**: the v2 INSERT data is converted into a compressed `.hibackup` archive with embedded metadata. No SQL commands from the dump are executed, and uploading does not modify the database.
4. Back up the destination's current data, then separately confirm restoring the converted file. Use advanced restore with users/roles and admin to copy logins; exclude settings to preserve DEV configuration.

Conversion accepts data-only dumps generated by the old application with `--column-inserts`, not arbitrary PostgreSQL dumps (such as `COPY`). Mismatched files, unsupported statements/tables/columns, and conflicting Alembic revisions are explicitly rejected. Restore still checks compatibility with the destination revision. Keep a copy of the source until you verify the migrated data. No standalone tool or connection from the new installation to the production database is required.

### Barcodes and QR codes

- Each item can have multiple barcodes (EAN/UPC/QR and others), managed from the item edit screen.
- The "Scan" button on inventory and checklist pages lets you use a camera (desktop or mobile), a USB/Bluetooth barcode reader (which acts like a keyboard), or manual entry. Camera access requires HTTPS (or localhost).
- An unknown code can be used to create an item or link the code to an existing one. Each code must be unique within its inventory.
- EAN lookup uses Open Food Facts, Open Beauty Facts, Open Pet Food Facts, and Open Products Facts; books (ISBN-10/13, normalized to ISBN-13) use Open Library with a Google Books fallback (set `GOOGLE_BOOKS_API_KEY` to avoid keyless quota limits). Medicines are recognized (EAN, 9-digit Italian AIC, GTIN extracted from the GS1 DataMatrix) but have no public per-code API, so details appear only if the sources above know them. It is free, requires no API key, and uses a local cache. Disable it by setting `BARCODE_LOOKUP_ENABLED=false`. When enabled, codes are sent to these external services.

### List-to-inventory assignments

- From an inventory item ("📋 Assign") or a shopping list ("📥 From inventory"), you can link a list entry to an inventory item and specify the quantity to take.
- Checking the entry subtracts the assigned quantity from the stock. If there is not enough stock, you can choose to set it to zero or cancel the action.
- Unchecking the entry within 45 seconds restores the stock. After 45 seconds, the stock remains unchanged and the assignment becomes active again (useful for recurring purchases). If you check the entry again within 45 seconds of a late uncheck, the action is cancelled without subtracting stock again.
- Inventory entries show both gross and net stock (gross stock minus assignments that have not yet been checked off).

### Anonymous telemetry (opt-in)

Telemetry is **disabled by default**: nothing is sent until you explicitly enable it. It is used to estimate how many installations are active and which versions they run.

To enable it, set this backend environment variable:

```yaml
TELEMETRY_ENABLED: "true"
```

Data is sent to the public endpoint defined by `DEFAULT_TELEMETRY_URL` in [telemetry_service.py](backend/telemetry_service.py). Anyone hosting their own endpoint can override it with the optional `TELEMETRY_URL` variable.

To disable it, remove `TELEMETRY_ENABLED` or set it to `false`, then restart the backend.

Once a day (and shortly after startup) the backend sends a single message with:

| Field | Description |
|---|---|
| `id` | Random identifier (UUID) generated locally on the first send, not linked to users or machines |
| `version` | Backend version |
| `inventories` | Number of inventories (checklists are not counted) |
| `channel` | Image channel: `release`, `dev` or `unknown` (local build) |
| `last_activity` | Date of the last change to inventories or items |

The **country** is not sent by the backend: the receiving server (Cloudflare) derives it from the request, and the IP address is not stored. Inventory or item names, users, passwords and any other content are never sent. If the server is unreachable, sending fails silently and does not affect the app.

The collection endpoint code (Cloudflare Worker + D1) is in [telemetry-worker/](telemetry-worker/).

The **About** tab in the sidebar shows the app versions and aggregated community statistics (active installations in the last 30 days, countries, versions and release/dev channels in use), read from the public `/public-stats` endpoint. This is a plain GET request made by the backend: it sends no installation data and works even when telemetry is disabled. To disable this read as well, set `ABOUT_STATS_ENABLED=false`.

### Publishing Docker images

Multi-platform images (amd64 and arm64) are published to both Docker Hub and GitHub Container Registry (GHCR).

#### With GitHub Actions (recommended)

The [publish-images.yml](.github/workflows/publish-images.yml) workflow publishes images in these cases:

| Event | Published tags |
|---|---|
| Push to `main` (only if `backend/`, `frontend/` or the workflow change; `.md` files are ignored) | `latest` and `<version>` |
| Manual run with `dev` channel (**Actions → Publish Docker images → Run workflow**, from any branch) | `dev` and `<version>-dev` |
| Manual run with `release` channel | `latest` and `<version>` |

Versions are read from `API_VERSION` in `backend/.env` and `version` in `frontend/package.json`.

Required setup:

- Repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.
- No secret is needed for GHCR: the workflow uses `GITHUB_TOKEN` with the `packages: write` permission. Each GHCR package must grant the repository **Write** access: under **Package settings → Manage Actions access**, add `napalmz/home-inventory`.

#### With the local script

Log in to both registries:

```bash
docker login
docker login ghcr.io -u napalmz
```

For GHCR, use a GitHub Personal Access Token (classic) with the `write:packages` permission instead of a password. Then run `./build_and_push.sh` for a release (`latest` and version tags), or `./build_and_push.sh dev` for the development channel (`dev` and `-dev` version tags). The script prompts separately whether to build and publish the backend and frontend.

#### Repository link and visibility

Both images include the OCI label `org.opencontainers.image.source` with this repository's URL. For existing GHCR packages, check or set the link manually: open **Packages** on your GitHub profile, select each package (`home-inventory-backend` and `home-inventory-frontend`), click **Connect repository**, and choose `napalmz/home-inventory`.

To make the images public, open **Package settings** for each package and change its visibility to **Public**. Repository linking and visibility are separate settings.

### Authors

- [@napalmz](https://www.github.com/napalmz)
