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
