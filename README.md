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

Per migrare sul posto una vecchia installazione, lascia le coppie `nome.sql` + `nome.sql.meta.json` nella cartella dei backup. Ogni backup SQL mostra solo **Converti** ed **Elimina** e non partecipa alle selezioni multiple. **Converti** crea `nome.hibackup` senza modificare il database o sovrascrivere un archivio esistente; soltanto al termine chiede se eliminare entrambi i sorgenti. Annullando la conferma, i sorgenti restano disponibili. **Elimina** chiede conferma e rimuove la coppia SQL, non l'eventuale `.hibackup`. Senza il file `.sql.meta.json` la conversione è disabilitata.

Gli amministratori possono confrontare i dati dalla pagina **Backup**:

- Seleziona un backup e premi **Confronta con DB corrente**: la direzione è backup (prima) verso DB corrente (dopo).
- Seleziona due backup e premi **Confronta 2 backup selezionati**: il primo selezionato è il prima, il secondo il dopo; **Inverti prima/dopo** scambia la direzione.
- Il riepilogo include tutte le tabelle applicative, anche utenti, impostazioni e storico. I dettagli mostrano record aggiunti, rimossi e modificati, con valori prima/dopo per campo, filtro per tabella e pagine da 50 record.
- I record sono associati per chiave primaria, anche composta: usa backup della stessa installazione. Password, hash, segreti riconosciuti e tutti i valori delle impostazioni sono oscurati; le relative modifiche vengono comunque conteggiate.

Il confronto è in sola lettura: non modifica il database o i backup e non esegue un ripristino. Sono confrontabili anche revisioni Alembic diverse con tabelle riconosciute; i controlli del ripristino restano invariati. Il DB corrente viene riletto a ogni cambio pagina o filtro, quindi modifiche concorrenti possono cambiare i risultati.

Il volume persistente va montato su `/app/data`, non sull'intera directory `/app`: il codice e i file runtime dell'immagine devono restare visibili. L'entrypoint è installato in `/usr/local/bin` così non viene nascosto da bind mount dell'applicazione.

Compose Dev usa il volume nominato `backenddata:/app/data`, come `pgdata` e
`mysqldata`: SQLite, backup e chiave JWT AUTO sono gestiti da Docker, senza
creare file dati nel repository. Il volume sopravvive alla ricreazione dei
container; `docker compose down -v` lo elimina insieme agli altri volumi.
Il passaggio dal precedente bind mount non copia automaticamente i dati:
la cartella `backend/data` resta intatta, ma il nuovo volume parte vuoto.
Prima del cambio salvare un backup applicativo e scaricarlo, poi ripristinarlo
nel nuovo ambiente. Per conservare anche i token esistenti, trasferire separatamente
il file chiave JWT mantenendo i permessi `0600`; altrimenti AUTO genera una
nuova chiave e occorre rifare login, senza perdere le password del DB ripristinato.
Su un volume nuovo impostare `ADMIN_PASSWORD` prima dell'avvio.
In Compose Dev inserirla nel file privato `backend/.env` (non versionato).
Senza password e senza un admin gia presente nel DB, il bootstrap fallisce
e il backend rimane unhealthy; il worker attende correttamente il backend.
Il controllo salute backend viene eseguito ogni 5 secondi, con timeout di
5 secondi, tolleranza iniziale di 60 secondi e 3 tentativi falliti.
Il file root `.env.dev` e versionato e caricato automaticamente dal Compose Dev,
anche con Compose Up da VS Code. Contiene solo default pubblici di test:
SQLite e timezone. Non inserire segreti reali. Per il backend viene caricato
 `backend/.env`: i default globali vengono quindi
sovrascritti dai valori specifici del backend, se presenti. Per cambiare
database solo localmente usare `backend/.env`, mantenendo coerenti
`DATABASE_TYPE` e `DATABASE_URL`. Le variabili
esplicite in `environment` mantengono la precedenza su entrambi i file.
Questo e un `env_file` dei servizi, non il file di interpolazione Compose:
`COMPOSE_PROFILES` al suo interno non attiverebbe profili. Su questo branch
il worker si abilita con `--profile notifications` oppure `COMPOSE_PROFILES=notifications`
nella shell o nel `.env` root privato, conservato localmente ma non versionato.
Backend e worker caricano gli stessi env file e condividono `backenddata:/app/data`.
Il codice backend proviene dall'immagine: dopo modifiche al codice occorre
ricostruire l'immagine e ricreare il container; il reload non legge i sorgenti host.

All'avvio il backend mostra il tipo di database e l'URL di destinazione con password mascherata e parametri query esclusi.

Il prefisso proxy `FASTAPI_ROOT_PATH` viene passato a Uvicorn dall'entrypoint Docker. Per un avvio locale dietro proxy usa `uvicorn main:app --reload --root-path /api`; senza proxy ometti `--root-path`.

Gli healthcheck Docker non conservano il corpo delle risposte riuscite. Il frontend usa `/health-check`, verificando che `index.html` sia disponibile; il backend mantiene `/system/health-check` (controllo del processo API, non della connessione DB). In Compose Dev il backend viene controllato ogni 5 secondi, con 60 secondi di tolleranza iniziale per bootstrap e migrazioni: il primo controllo riuscito lo rende subito healthy e sblocca il worker, senza attendere la fine della tolleranza. Gli intervalli di produzione restano invariati. I controlli riusciti non producono access log; gli errori e le normali richieste restano visibili. Per applicare le modifiche al Compose Dev basta ricreare il container backend; le modifiche alle immagini richiedono anche ricostruzione o aggiornamento.

Se nei log compare `ModuleNotFoundError: No module named 'database'`, verifica che lo stack non monti una cartella dati su `/app`. Ad esempio, sostituisci `.../home-inventory-dev:/app` con `.../home-inventory-dev:/app/data` e ricrea il container. Se i backup erano nella sottocartella `backups`, il nuovo mount li espone direttamente in `/app/data/backups`. Non occorre modificare il volume PostgreSQL.

Per lo sviluppo locale, `./backend/setup_venv.sh` prepara `backend/.venv` usando il solo `backend/requirements.txt`, indipendentemente dalla directory da cui viene lanciato. Questo script non viene usato nel container Docker.

### Chiave JWT e configurazione privata

I file `.env` privati non sono tracciati (il pubblico `.env.dev` fa eccezione);
`backend/.dockerignore` esclude env,
dati persistenti e file chiave dall'immagine. Per lo sviluppo copiare
`backend/.env.example` in `backend/.env` e impostare `ADMIN_PASSWORD` prima
del primo avvio. Il Compose Dev carica questo file opzionale (richiede Docker
Compose 2.24+); i valori `SECRET_KEY` e `SECRET_KEY_FILE` del servizio sono
invece configurati dalla shell o dal `.env` della root, con default `AUTO`
e vuoto. Per produzione impostare `ADMIN_PASSWORD` nella shell/`.env` root
solo per creare l'admin iniziale; non modifica password di account esistenti.

- `SECRET_KEY=AUTO` o assente: genera una chiave casuale in
  `/app/data/jwt-secret.key` (in locale `backend/data/jwt-secret.key`), con
  permessi `0600`; ai riavvii la riutilizza. La creazione e atomica anche
  con richieste concorrenti. Conservare il volume dati anche con PostgreSQL/MySQL.
- `SECRET_KEY` esplicita: usa quella, almeno 32 byte; generarla casualmente,
  ad esempio con `openssl rand -hex 64`, e conservarla fuori da Git.
- `SECRET_KEY_FILE`: legge un file montato, ad esempio un Docker secret.
  Non impostare contemporaneamente una `SECRET_KEY` esplicita; `AUTO` e
  compatibile con `SECRET_KEY_FILE`. Errori di file/configurazione bloccano
  l'avvio senza ripiegare su chiavi temporanee.
- I log indicano generazione, riutilizzo o configurazione esterna, mai la
  chiave. Non copiare segreti in log, ticket o screenshot.

Esempio Docker secret (da aggiungere al Compose, con il file fuori dal repository):

```yaml
services:
  backend:
    environment:
      SECRET_KEY: AUTO
      SECRET_KEY_FILE: /run/secrets/jwt_key
    secrets:
      - jwt_key
secrets:
  jwt_key:
    file: /percorso/privato/jwt-key.txt
```

Le variabili gia presenti nell'ambiente prevalgono su `load_dotenv`.
Tutte le repliche API devono usare la stessa chiave, tramite file/secret
condiviso o configurazione esplicita. Perdita del file AUTO o rotazione
invalida i token e richiede un nuovo login, **non cancella password o dati**.
I backup applicativi del DB non includono il file chiave: proteggerlo e
gestirlo separatamente; un restore DB non lo sovrascrive.
Le vecchie chiavi distribuite su Git/immagini vanno considerate esposte:
ricostruire le immagini e ruotarle. La rimozione attuale non riscrive la
cronologia Git ne cancella le immagini gia pubblicate.
Il file locale `backend/.env` preesistente viene conservato ma ignorato da
Git: per avvio Python diretto una vecchia `SECRET_KEY` li presente continua
a prevalere su AUTO; sostituirla con `AUTO` o con una nuova chiave privata.

Test dopo ricostruzione e ricreazione del backend: verificare nei log
`generated` al primo avvio AUTO e `reused` al successivo, rifare login con
la password esistente e controllare che il token resti valido dopo il
riavvio. Con chiave esplicita/file verificare il messaggio di configurazione,
mai il suo valore. Provare una rotazione soltanto sull'installazione di test:
il vecchio token deve dare 401 e un nuovo login deve riuscire.

#### Operazioni amministrative di sicurezza

In **Impostazioni > Sicurezza**, solo gli amministratori possono:

- **Revocare tutte le sessioni**, senza cambiare la chiave JWT.
- **Ruotare la chiave automatica**, sostituendo atomicamente il file AUTO
  e revocando anche tutte le sessioni.

Sono operazioni separate, entrambe con password corrente e conferma esplicita.
Prima della revoca, la stessa schermata mostra le sessioni non ancora revocate
di tutti gli utenti in un box scorrevole adatto anche al mobile, con dispositivo,
accesso, scadenza e indicazione della sessione corrente. Le sessioni scadute
sono distinguibili ma incluse, come nella revoca globale. Usare **Aggiorna elenco**
per rileggere lo stato; eventuali token legacy non tracciati non sono elencati,
ma vengono comunque invalidati.
Tutti gli utenti, incluso chi esegue l'operazione, devono rifare login;
password e dati non cambiano. Dopo cinque password errate in cinque minuti,
le conferme sono temporaneamente bloccate. Se la chiave proviene da
`SECRET_KEY` o `SECRET_KEY_FILE`, la rotazione da UI/API e bloccata con
**Rotazione gestita tramite configurazione dell'installazione**; la revoca
resta disponibile.

Il setting protetto `DEVICE_SESSION_RETENTION_DAYS` viene creato automaticamente
con default **30 giorni**, modificabile in **Impostazioni > Generale > Parametri
protetti** (intero positivo). La pulizia parte circa un minuto dopo l'avvio
e si ripete ogni 24 ore, anche senza backup automatici: elimina le sessioni
terminate da oltre la finestra, contando dal primo evento tra disconnessione
e scadenza. Le sessioni ancora attive e l'audit di sicurezza non vengono
eliminati. La modifica del valore viene letta alla successiva pulizia,
senza riavvio; le sessioni eliminate spariscono anche da Gestione profilo.
Per anticipare la pulizia, **Pulisci sessioni scadute / disconnesse** in
Gestione profilo elimina solo le proprie sessioni terminate; in Sicurezza
gli admin possono eseguire la stessa pulizia per tutti gli utenti.
Non richiede password, ignora la retention e non revoca sessioni attive.
Anche l'elenco dispositivi in Gestione profilo scorre internamente, con
altezza limitata e titolo/pulsante di pulizia esterni al box.
Aprendo un link protetto senza sessione (o con token scaduto), il login
conserva la pagina richiesta, inclusi query string e frammento, anche dopo
un aggiornamento della pagina di login o la registrazione. Dopo l'accesso
si torna a quel percorso; il login diretto torna alla home. Destinazioni
esterne non sono ammesse e i permessi della pagina restano invariati.

Le repliche AUTO devono condividere sia il file chiave sia il file lock
nello stesso volume dati. Login e rotazione sono coordinati e ogni processo
rilegge la chiave senza richiedere riavvii. Le altre richieste rilevano la
revoca al successivo controllo di autenticazione.

La migrazione `d6e7f8a9b0c1` aggiunge l'audit tecnico, consultabile nella
stessa schermata: attore, data UTC, azione, esito e numero di sessioni revocate,
mai password o chiavi. Non eliminare questo audit: conserva anche il limite
temporale usato per invalidare i token precedenti. Se la rotazione fallisce
dopo la revoca, le sessioni restano revocate. Un esito `pending` indica
un'interruzione o un errore nella conferma finale: verificare i log prima
di riprovare, senza presumere che la chiave sia rimasta invariata.

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

### Priorità checklist

Le righe delle checklist hanno una priorità da **−2** (molto bassa) a **+2** (molto alta), con **0** come valore predefinito. Impostala durante la creazione o la modifica e ordina la lista per priorità; un indicatore colorato distingue priorità alte, medie e basse. La priorità non si applica agli articoli degli inventari e viene azzerata quando una riga viene spostata in un inventario.

### Cronologia e audit

Gli aggiornamenti senza modifiche effettive non creano nuove versioni: una descrizione `null` e una stringa vuota sono equivalenti, così come i metadati numerici con lo stesso valore ma diversa formattazione. Creazioni, eliminazioni e modifiche reali continuano a essere registrate.

Le differenze equivalenti presenti nello storico precedente non vengono mostrate nell'interfaccia. I record storici e gli snapshot usati per il ripristino non vengono modificati.

In Compose Dev backend, worker e frontend leggono `TZ` da `.env.dev`; il file
opzionale `backend/.env` prevale per backend e worker. In produzione la timezone
di tutti i servizi viene da `TZ` nella shell/`.env` root (default `Europe/Rome`),
condivisa tramite anchor YAML.

### Notifiche (in sviluppo)

La feature e in sviluppo per fasi sul branch `38-feature-device-notification-on-logged-device`: tutte le PR delle sub-issue confluiscono in questo branch e solo dopo le sette fasi viene aperta la PR verso `release/1.6.0`. Vedi [piano, stato e test manuali](docs/notifications.md). La fase 3 aggiunge regole configurabili via API e inbox nel database, elaborata dal worker opt-in (profilo Compose `notifications`). La fase 4 aggiunge il backend Web Push/VAPID, disabilitato di default e legato alle sessioni. La fase 5 aggiunge consenso browser, service worker minimo e gestione da Profilo; editor preferenze e inbox frontend restano fasi successive. Nessuna regola viene preattivata. [Configurazione VAPID e restore](docs/notifications.md#fase-4-web-push-backend-e-sessioni); [test e limiti della fase 5](docs/notifications.md#fase-5-service-worker-e-consenso-browser).

Sottoscrizioni e code push transitorie sono escluse dai backup/confronti DB e
svuotate al restore, per non riattivare consensi o invii obsoleti.

Le notifiche quantita accorpano le correzioni nella stessa finestra della cronologia (45 secondi, costante condivisa); tornare al valore iniziale annulla l'avviso pendente. Anche il completamento checklist attende questa finestra. Entrambi i Compose controllano la salute del worker tramite heartbeat e query DB; dettagli e log nel [monitoraggio worker](docs/notifications.md#monitoraggio-worker).

### Automazioni agentiche (GitHub Copilot)

Tre workflow GitHub Agentic usano Copilot solo su avvio manuale: Sentinel, Bolt e Palette. Non sono previste esecuzioni schedulate. Dalla scheda **Actions**, scegli il workflow, premi **Run workflow** e seleziona il branch in **Use workflow from** (default `main`). Il branch selezionato viene analizzato ed è la base della PR proposta. Da CLI: `gh workflow run palette.lock.yml --ref release/1.6.0` (sostituisci `palette` con `sentinel` o `bolt`; senza `--ref` viene usato `main`). Il branch deve contenere il workflow. Se trovano un intervento adatto, creano al massimo una PR in bozza; non effettuano merge automatici. Sentinel è limitato a hardening preventivo generico e non cerca né pubblica dettagli su vulnerabilità specifiche, perché il repository è pubblico.

Per abilitarli, GitHub Actions deve essere attivo e l'organizzazione deve consentire l'uso di Copilot CLI fatturato all'organizzazione. Le sorgenti sono i file `.md` in `.github/workflows`; dopo averli modificati, rigenera i workflow Actions con `gh aw compile`. Non modificare direttamente i corrispondenti file `.lock.yml` generati.

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

Le versioni per la pubblicazione sono lette da `backend/VERSION` e da `version` in `frontend/package.json`. `backend/VERSION` e anche l'unica fonte della versione API, healthcheck e telemetria: per una nuova release aggiornare quel file e ricostruire l'immagine. La variabile ambiente `API_VERSION` non viene piu utilizzata.

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

For in-place migrations, leave `name.sql` + `name.sql.meta.json` pairs in the backup directory. Each SQL backup only offers **Converti** and **Elimina**, and is excluded from bulk selections. **Converti** creates `name.hibackup` without modifying the database or overwriting an existing archive; only after success does it ask whether to delete both source files. Canceling keeps the sources. **Elimina** confirms deletion of the SQL pair, not any converted `.hibackup`. Conversion is disabled when `.sql.meta.json` is missing.

Administrators can compare data on the **Backup** page:

- Select one backup and click **Confronta con DB corrente**: the direction is backup (before) to current database (after).
- Select two backups and click **Confronta 2 backup selezionati**: the first selected is before, the second is after; **Inverti prima/dopo** reverses the direction.
- Summaries include every application table, including users, settings and history. Details show added, removed and modified records, with before/after field values, a table filter and pages of 50 records.
- Records are matched by primary key, including composite keys: use backups from the same installation. Passwords, hashes, recognized secrets and all settings values are redacted; their changes are still counted.

Comparison is read-only: it neither modifies the database or backups nor performs a restore. Different Alembic revisions can be compared when their tables are recognized; restore compatibility checks are unchanged. The current database is read again for each page or filter change, so concurrent updates can change results.

Mount persistent storage at `/app/data`, not over the entire `/app` directory: the image's application code and runtime files must remain visible. The entrypoint is installed in `/usr/local/bin` so application bind mounts cannot hide it.

Compose Dev uses the named volume `backenddata:/app/data`, like `pgdata` and
`mysqldata`: Docker manages SQLite, backups and the AUTO JWT key without
creating data files in the repository. The volume survives container recreation;
`docker compose down -v` deletes it along with other volumes.
Switching from the previous bind mount does not copy data automatically:
`backend/data` is left untouched, but the new volume starts empty. Before
switching, create and download an application backup, then restore it in the
new environment. Transfer the JWT key separately with `0600` permissions to
preserve existing tokens; otherwise AUTO generates a new key and requires
login again, without losing restored password hashes. Set `ADMIN_PASSWORD`
before starting with a new volume.
Backend code comes from the image: rebuild it and recreate the container after
code changes; reload does not read host source files.

The root `.env.dev` is tracked and loaded automatically by Compose Dev,
including VS Code Compose Up. It contains public test defaults only: SQLite
and timezone, never real secrets. The backend loads it before optional
`backend/.env`, whose backend-specific values override the global defaults.
Use `backend/.env` for local database overrides, keeping `DATABASE_TYPE` and
`DATABASE_URL` consistent. Explicit service `environment` entries still take precedence over
both files. This is a service `env_file`, not a Compose interpolation file:
putting `COMPOSE_PROFILES` there does not activate profiles. On this branch,
enable the worker through `--profile notifications` or the shell/private root
`.env`. Backend and worker load the same env files and share the data volume.

At startup, the backend logs the database type and destination URL with the password masked and query parameters omitted.

The Docker entrypoint passes the `FASTAPI_ROOT_PATH` proxy prefix to Uvicorn. For local startup behind a proxy, use `uvicorn main:app --reload --root-path /api`; without a proxy, omit `--root-path`.

Docker healthchecks discard successful response bodies. The frontend uses `/health-check`, checking that `index.html` is available; the backend keeps `/system/health-check` (API process liveness, not database connectivity). In Compose Dev the backend is checked every 5 seconds, with a 60-second startup grace period for bootstrap and migrations: the first successful probe immediately marks it healthy and unblocks the worker, without waiting for the grace period to end. Production intervals remain unchanged. Successful probes do not produce access logs; errors and normal requests remain visible. Applying the Compose Dev changes only requires recreating the backend container; image changes also require rebuilding or updating images.

If logs show `ModuleNotFoundError: No module named 'database'`, check that the stack does not mount a data directory over `/app`. For example, replace `.../home-inventory-dev:/app` with `.../home-inventory-dev:/app/data` and recreate the container. Existing backups in the `backups` subdirectory will then be available at `/app/data/backups`. Leave the PostgreSQL volume unchanged.

For local development, `./backend/setup_venv.sh` prepares `backend/.venv` using only `backend/requirements.txt`, regardless of the directory it is launched from. Docker containers do not use this script.

### JWT key and private configuration

Private `.env` files are untracked (public `.env.dev` is the exception) and
excluded from backend image builds, along
with persistent data and key files. Copy `backend/.env.example` to
`backend/.env` for development and set `ADMIN_PASSWORD` before creating the
initial admin. Compose Dev loads that optional file (Compose 2.24+ required).
Both Compose files take `SECRET_KEY` and `SECRET_KEY_FILE` from the shell or
root `.env`, defaulting to `AUTO` and empty. Production takes the initial
`ADMIN_PASSWORD` from the shell/root `.env`; existing passwords are unchanged.

With `SECRET_KEY=AUTO` or no key configured, a random installation key is
atomically stored at `/app/data/jwt-secret.key` with owner-only permissions
and reused on restart. Keep this volume persistent, including when using an
external database. Alternatively provide a random `SECRET_KEY` of at least
32 bytes, or mount a Docker secret and set `SECRET_KEY_FILE` to its path
(leave `SECRET_KEY=AUTO` in that case). Invalid configuration fails startup,
without temporary-key fallbacks. Logs show the source/mode, never the key.

All API replicas must share a key. Losing or rotating it invalidates tokens
but does not affect password hashes or application data. Database backups do
not include this file: manage it separately. Previous keys published in Git
or images are exposed and must be rotated; this change does not rewrite
history or remove old images. Existing local env files remain on disk:
replace their old key with AUTO or a new private key for direct Python runs.

After rebuilding/recreating the backend, check `generated` then `reused`
across restarts and confirm login with the existing password. Confirm tokens
survive restart with a stable key; after a deliberate test key rotation, old
tokens must fail while a new login succeeds. See the [Italian configuration
examples](#chiave-jwt-e-configurazione-privata) for Docker secrets.

**Settings > Sicurezza** provides two separate admin-only actions: revoke
all sessions without changing the signing key, and rotate the automatically
managed key while also revoking every session. Both require the current
admin password and explicit confirmation; five failed confirmations within
five minutes temporarily block further attempts. Every user, including the
caller, must log in again. Passwords and application data are unaffected.
The same page lists all users' unrevoked sessions in a mobile-friendly
scrollable box, including expired sessions and a current-session marker.
Refresh the list to check recent logins; untracked legacy tokens are not listed
but are also invalidated by global revocation.
Externally supplied keys cannot be rotated through the UI/API.

The protected `DEVICE_SESSION_RETENTION_DAYS` setting is created automatically
with a default of **30 days** and accepts positive integer values. Cleanup runs
about one minute after startup and every 24 hours, independently of backups,
using the current setting. It deletes sessions whose first termination
(revocation or expiry) is older than that window, leaving active sessions
and security audit records untouched. Deleted sessions disappear from Profile.
Manual cleanup buttons in Profile (own sessions) and Security (admin, all users)
immediately delete expired/revoked sessions regardless of retention, without
password confirmation or logging out active devices.
The Profile device list also scrolls internally within a bounded height,
keeping its heading and cleanup button outside the scrollable area.
Login redirects from protected links or expired sessions preserve the requested
path, query and fragment, including across login refresh and registration.
Direct login defaults to Home. Only internal return paths are accepted;
page authorization rules still apply.

AUTO replicas must share the key and lock files on persistent storage;
processes reload atomic key replacements without restarting. Migration
`d6e7f8a9b0c1` adds the security audit displayed on the same page. Keep its
records, which also enforce revocation of older tokens. Failed rotations
leave sessions revoked; `pending` means final confirmation was interrupted
or failed, so check logs before retrying. No keys or passwords are audited.

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

### Checklist priorities

Checklist entries have a priority from **−2** (very low) to **+2** (very high), with **0** as the default. Set it when creating or editing an entry, and sort the list by priority; a colored indicator distinguishes high, medium, and low priorities. Priority does not apply to inventory items and is reset when an entry is moved to an inventory.

### History and audit

Updates with no effective changes do not create new versions: a `null` description and an empty string are equivalent, as are numeric metadata values with different formatting but the same value. Creations, deletions, and actual changes are still recorded.

Equivalent differences in existing history are hidden in the interface. Historical records and snapshots used for restoration are not modified.

Compose Dev loads `TZ` from `.env.dev`; optional `backend/.env` overrides it
for both backend and worker, which share `backenddata:/app/data`. Production
shares shell/root `.env` timezone configuration through a YAML anchor
(default `Europe/Rome`). Enable the worker with `--profile notifications`
or `COMPOSE_PROFILES=notifications` in the shell/private root `.env`.

### Notifications (in development)

The feature is being developed in gated phases on `38-feature-device-notification-on-logged-device`: all sub-issue PRs target this branch, with a final PR into `release/1.6.0` only after all seven phases. See [plan, status and manual checks (Italian)](docs/notifications.md). Phase 3 adds API-configured rules and a database inbox processed by the opt-in worker (Compose profile `notifications`). Phase 4 adds a session-bound Web Push/VAPID backend, disabled by default. Phase 5 adds browser consent, a minimal service worker and profile controls; preference editing and the frontend inbox remain for later phases. No rules are enabled automatically. See [VAPID configuration and restore limits](docs/notifications.md#fase-4-web-push-backend-e-sessioni) and [phase 5 checks and limitations](docs/notifications.md#fase-5-service-worker-e-consenso-browser).

Transient push subscriptions and delivery queues are excluded from backups/DB
comparisons and cleared on restore to prevent obsolete consent or send replay.

Quantity notifications coalesce corrections within the same window as history (45 seconds, shared constant); returning to the initial value cancels the pending alert. Checklist completion also waits for this window. Both Compose files check worker health using a heartbeat and database query; see [worker monitoring (Italian)](docs/notifications.md#monitoraggio-worker).

### Agentic workflows (GitHub Copilot)

Three GitHub Agentic workflows use Copilot only when manually dispatched: Sentinel, Bolt, and Palette. There are no scheduled runs. From the **Actions** tab, choose the workflow, click **Run workflow**, and select the branch under **Use workflow from** (default `main`). The selected branch is analyzed and used as the base of the proposed PR. From the CLI: `gh workflow run palette.lock.yml --ref release/1.6.0` (replace `palette` with `sentinel` or `bolt`; omitting `--ref` uses `main`). The branch must contain the workflow. If they find a suitable improvement, they create at most one draft PR; they never merge automatically. Sentinel is restricted to generic preventive hardening and does not search for or publish details about specific vulnerabilities because this repository is public.

To enable them, GitHub Actions must be enabled and the organization must allow Copilot CLI usage billed to the organization. The workflow sources are the `.md` files in `.github/workflows`; after editing them, regenerate the Actions workflows with `gh aw compile`. Do not edit the corresponding generated `.lock.yml` files directly.

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

Publishing versions are read from `backend/VERSION` and `version` in `frontend/package.json`. `backend/VERSION` is also the single source for the API, healthcheck and telemetry version: update it and rebuild the image for a new release. The `API_VERSION` environment variable is no longer used.

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
