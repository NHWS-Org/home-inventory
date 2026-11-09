# Notifiche: preferenze personali e Web Push

Epic: [#38](https://github.com/NHWS-Org/home-inventory/issues/38).
Le PR delle fasi sono destinate a `38-feature-device-notification-on-logged-device`,
non direttamente a release o main. Ogni fase si ferma dopo test automatici e PR,
in attesa dei test e dell'approvazione dell'utente.

## Modello aggiornato

Le notifiche non richiedono configurazioni per inventario/lista. Ogni utente
sceglie in **Profilo > Gestione profilo > Preferenze notifiche** quali modifiche
ricevere. I destinatari sono gli utenti non bloccati che possono **modificare**
il contenitore, secondo gli stessi controlli delle API di modifica.
Gli utenti viewer e le condivisioni in sola lettura non ricevono questi eventi.
Accessi, ruolo e preferenze vengono rivalutati dal worker e prima degli invii.
Nel modello attuale non esistono permessi lettura/scrittura per singola
condivisione: il ruolo viewer e in sola lettura, il moderator puo modificare
i contenitori propri o condivisi e l'admin puo modificare tutti i contenitori.
Di conseguenza, le preferenze operative degli admin riguardano tutti i
contenitori; le loro azioni restano escluse di default.
Nel Profilo dei viewer viene mostrata una spiegazione, senza controlli di
preferenza o richiesta del consenso push per eventi che non possono ricevere.

| Evento | Quando | Inbox predefinita |
|---|---|---|
| `item_quantity_changed` | Qualsiasi variazione di quantita o spunta di una singola riga | Attiva |
| `item_updated` | Modifica effettiva di nome, descrizione, barcode, metadati o altri dettagli di un elemento | Disattiva |
| `inventory_updated` | Modifica effettiva del contenitore, attualmente il nome | Disattiva |

I valori predefiniti valgono per utenti nuovi e per l'inizializzazione della
migrazione. Il push e sempre disattivato di default e richiede due consensi:
preferenza personale per evento e attivazione esplicita del browser.
Le azioni proprie sono escluse salvo scelta di **Mie azioni**.
Inbox e push sono indipendenti.

La sezione e compatta: ogni tocco su Inbox, Push o Mie azioni salva
automaticamente. Durante la richiesta i controlli sono disabilitati per evitare
scritture concorrenti. Un errore ripristina il valore precedente e mostra
esplicitamente come riprovare.

### Quantita e spunte: grace period

Le correzioni accorpabili (stesso elemento, stesso attore, sole quantita)
condividono la finestra della cronologia: **45 secondi dall'ultima modifica
effettiva**, definita in `backend/quantity_changes.py`.
La notifica rappresenta la variazione netta; tornare al valore iniziale
entro la finestra annulla l'evento pendente. Un no-op non prolunga la finestra.
Gli eventi gia elaborati non possono essere ritirati.

Non esiste piu una soglia: aumenti e diminuzioni sono entrambi notificabili.
Nelle checklist ogni spunta o rimozione di spunta e una modifica indipendente:
non occorre completare tutta la lista. Le altre modifiche di dettaglio non
usano il grace period delle quantita.

### Centro notifiche

La campanella mostra il numero di notifiche non lette accessibili, aggiornato
ogni 30 secondi, al focus e dopo la lettura. Un errore non viene mostrato come zero.
Con notifiche non lette l'icona oscilla su desktop e mobile; l'animazione si
ferma a zero e rispetta la preferenza di sistema per ridurre il movimento.
La voce è nella sidebar desktop e nella barra di navigazione inferiore mobile;
il badge mostra solo i conteggi positivi (massimo visibile 99+), mai zero.
Su mobile il titolo Centro notifiche compare nel header comune alle altre pagine.
La inbox elenca 50 righe per volta con Carica altre, Aggiorna, lettura singola
e Segna tutte come lette. La lettura globale riguarda tutte le pagine.
L'ordine e decrescente per data/ora dell'azione (ID come spareggio), non per
ordine di consegna del worker, e viene applicato prima della paginazione.

Contenitori non piu modificabili non vengono elencati, conteggiati o modificati
dalla lettura massiva. I link usano il tipo del contenitore autorizzato dal
backend; le route verificano nuovamente i permessi all'apertura.
La cancellazione di un inventario/lista o item elimina i relativi eventi e le
notifiche/code associate: il riutilizzo degli ID SQLite non ricollega vecchi
avvisi a nuove risorse. Anche gli eventi preesistenti vengono esclusi se la
risorsa corrente e stata creata dopo l'evento.
Aprire direttamente un inventario o una lista non segna le notifiche come lette.
La freccia di una notifica non letta apre la risorsa e segna letta solo quella
notifica; un errore resta visibile con la possibilità di riprovare. Il click su
un banner push apre invece la risorsa con l'UUID evento nel link:
dopo autenticazione l'app segna come letta solo la notifica di quell'evento
appartenente all'utente corrente e aggiorna la campanella. Il parametro viene
rimosso dopo il successo; login conserva la destinazione. Account diverso,
accesso revocato o errore di rete non marcano altre notifiche e mostrano errore
con possibilita di riprovare. Il worker non accede a token o API autenticate.
Con solo push e inbox disattivata non c'e una riga inbox da segnare come letta.
Lo stato letto riguarda la inbox, non certifica consegna o visualizzazione push.
Le righe compatte mostrano icona inventario/lista, nome, elemento e azione
(quantita con delta firmato, spunta, titolo/descrizione aggiornati), data/ora
dell'azione e pulsanti a destra per aprire inventario/lista o segnare letto.
Il pulsante di lettura resta visibile dopo la lettura, grigio e disabilitato
con etichetta "Gia letta", mantenendo stabile il layout delle azioni.
Titolo e descrizione sono salvati nell'evento, non ricavati dal valore corrente:
una modifica successiva non riscrive il dettaglio storico. Per eventi precedenti
senza dettagli viene indicato il campo modificato; per barcode/metadati e
assegnazioni viene indicata la categoria, senza inventare valori storici.
Il payload push di sistema include i dettagli descritti sotto. Non serve una migrazione DB.

### API

Tutti gli endpoint sono autenticati e limitati all'utente del token:

| Metodo | Percorso | Risultato |
|---|---|---|
| GET | `/notifications?limit=50&offset=0` | Inbox autorizzata con tipo/nome contenitore |
| GET | `/notifications/unread-count` | `{count}` |
| PUT | `/notifications/{id}/read` | Lettura singola |
| PUT | `/notifications/events/{event_key}/read` | Lettura dell'evento del banner, solo propria inbox |
| PUT | `/notifications/read-all` | `{updated}`, tutte le pagine autorizzate |
| GET | `/notifications/preferences` | Preferenze personali dei tre eventi |
| PUT | `/notifications/preferences/{event_type}` | Canali e azioni proprie |

Non esistono endpoint o editor per configurazioni condivise di notifica.

## Aggiornamento del database

La migrazione `a9b0c1d2e3f4` elimina la tabella delle vecchie regole e
inizializza le tre preferenze personali per ogni utente esistente.
**Elimina tutte le vecchie notifiche, gli eventi, gli invii e le preferenze**,
incluse le scelte precedenti sulla quantita; non li reinterpreta come nuovi
avvisi. Sessioni, sottoscrizioni browser e chiavi restano intatte, ma il nuovo
push per evento e disattivato. Gli utenti nuovi senza righe persistenti usano
gli stessi default all'accesso alle preferenze e alla valutazione degli eventi.
Le revisioni Alembic gia applicate
restano nella catena storica, per aggiornare anche installazioni esistenti;
non fanno parte del modello ORM o delle API attuali.

Prima dell'aggiornamento fare un backup e fermare API/worker. Ricostruire i
container e lasciare applicare le migrazioni al backend prima di riavviare il
worker. Non eseguire il vecchio worker sullo schema aggiornato.
Il downgrade di questa transizione non ricostruisce dati eliminati: richiede
il ripristino del backup.

## Outbox e worker

Gli eventi sono inseriti nella stessa transazione delle modifiche, senza commit
autonomi o invii di rete durante la richiesta. UUID stabile, deduplicazione
evento/utente e coda push separata rendono idempotenti gli effetti DB.

Claim atomico, lease di 60 secondi e fencing impediscono a worker obsoleti di
completare gli eventi. Errori temporanei: massimo cinque tentativi con backoff
30/60/120/240 secondi. Payload/versioni invalidi o scadenza diventano failed,
con codici errore tecnici, senza contenuti privati nei log.

Il worker e separato da uvicorn e APScheduler, abilitato dal profilo Compose
`notifications`. Aspetta il backend healthy e non applica migrazioni:

```sh
docker compose -f docker-compose-dev.yml --profile notifications up --build -d
docker compose -f docker-compose-dev.yml logs --tail=80 notification-worker
docker compose -f docker-compose-dev.yml exec notification-worker python -m notification_worker --status
```

### Monitoraggio worker

Entrambi i Compose controllano heartbeat e query DB. Una coda vuota e sana;
`completed` significa elaborazione DB conclusa, non consegna push.
Non usare vecchie immagini backend prive del contratto aggiornato.

## Fase 4: Web Push backend e sessioni

### Configurazione dell'installazione

Web Push e disabilitato di default. Configurare **sia API sia worker**:

```dotenv
WEB_PUSH_ENABLED=true
WEB_PUSH_VAPID_PRIVATE_KEY_FILE=/app/data/private_key.pem
WEB_PUSH_VAPID_SUBJECT=mailto:amministratore@example.com
```

In Dev usare il file privato `backend/.env`; in produzione shell o `.env` root.
Il PEM deve essere leggibile nello stesso percorso da entrambi i servizi.
Non inserire chiavi nel repository, in `.env.dev` o nell'immagine.
Generare una coppia P-256 una sola volta:

```sh
docker compose -f docker-compose-dev.yml exec backend sh -c \
  'cd /app/data && test ! -e private_key.pem && test ! -e public_key.pem && umask 077 && vapid --gen'
```

Il comando rifiuta di sovrascrivere chiavi. L'API deriva la chiave pubblica dal
PEM privato; non crea chiavi effimere. Configurazione mancante/corrotta con push
abilitato: API `503`, worker non avviabile. La chiave JWT e indipendente.
Cambiare VAPID richiede rinnovo delle sottoscrizioni browser.

### Sessioni, invii e limiti

Gli endpoint `/notifications/push/config`, `/subscriptions` e `/deliveries`
gestiscono configurazione pubblica, sottoscrizioni della sessione e risultati
tecnici. Il backend ricava user/session ID dal JWT. Il POST sottoscrizione
richiede `consent: true`, endpoint HTTPS e chiavi P-256 valide.
Una sottoscrizione non viene trasferita ad altro account.

Prima di ogni tentativo si ricontrollano sessione, blocco utente, generazione,
VAPID, preferenza, azioni proprie e permesso di modifica. Logout/revoca/blocco
impediscono nuovi invii; un messaggio gia affidato al provider non e ritirabile.
Eventi precedenti al consenso non producono push retroattivi.

Host consentiti: `fcm.googleapis.com`, `updates.push.services.mozilla.com`,
`web.push.apple.com`. Solo HTTPS, IP pubblici validati e DNS pinning; niente
redirect, host arbitrari o proxy ambientali.

I banner desktop/mobile mostrano tipo e nome inventario/lista nel titolo,
nome item e modifica nel testo (delta quantita, spunta, titolo/descrizione,
categorie barcode/metadati). Il click apre direttamente inventario/lista,
con normale verifica login/accessi. Titolo massimo 80 caratteri e testo 500,
con ellissi per valori lunghi; l'OS puo troncare ulteriormente le anteprime.
I contenuti sono cifrati con Web Push ma visibili anche sulla schermata bloccata
se le impostazioni OS lo consentono. Il Profilo avvisa esplicitamente di questo
comportamento. Nessuna nuova sottoscrizione automatica o prompt forzato.
`201`/`202` indicano accepted dal provider, non consegnata o letta.
TTL provider 300 secondi; coda al massimo 24 ore. Endpoint `404`/`410` eliminati.
`429`/`5xx` ritentati con backoff; timeout/crash ambigui diventano uncertain e
non vengono riprodotti automaticamente.

### Backup e restore

Backup logici e snapshot escludono sottoscrizioni e code push. Il restore
applicativo svuota inbox/outbox e dati push, senza ripristinare consensi o invii.
Per restore fisico del DB/volume, fermare API e worker, applicare migrazioni e,
prima del riavvio, eseguire nello stesso ambiente:

```sh
python -m notification_worker --reset-push
```

Il comando elimina sottoscrizioni/invii, non inventari. Conservare la chiave
privata in backup separato protetto.

## Fase 5: service worker e consenso browser

`frontend/public/push-sw.js` non intercetta fetch, non usa Cache Storage e non
legge API autenticate. Mostra i dettagli ricevuti nel push e permette solo link same-origin.
La route protetta `/notifications` conserva la destinazione attraverso login.

Il pannello Profilo distingue supporto, HTTPS, permesso negato, servizio
disabilitato, sottoscrizione scaduta e errori. Il prompt parte solo dal pulsante
esplicito, prima del lavoro asincrono. Logout/cambio account/revoche puliscono
server e browser; un errore di cleanup viene segnalato e non blocca logout.
La sezione collassata mostra lo stato push del browser corrente; il conteggio
dispositivi indica le sessioni attive, escludendo quelle scadute e revocate.
Il badge verde richiede anche il permesso del browser esplicitamente concesso;
con permesso negato o non ancora concesso il badge non è attivo, anche se
esiste ancora una sottoscrizione precedente da rimuovere o riattivare.
Durante la verifica o in caso di errore gli indicatori mostrano uno stato
distinto, non un risultato negativo o un conteggio pari a zero.
Se la disattivazione dal Profilo fallisce, l'associazione locale resta disponibile
per riprovare la pulizia; in caso di sottoscrizione scaduta e possibile sia
riattivarla sia disattivarla.
Con l'attivita dell'utente, il rinnovo della sessione sotto il 50% estende anche
la sottoscrizione push confermata dal browser, rispettandone la scadenza nativa.
Se la verifica fallisce, la sessione puo rinnovarsi ma il push no: un avviso
invita a controllare l'attivazione nel Profilo. Il polling non rinnova sessioni.

Mostra notifica di prova e un **test locale**, non un invio provider.
Su iOS/iPadOS serve 16.4+, HTTPS e app aggiunta alla schermata Home da Safari.
Focus e impostazioni OS possono impedire visualizzazione.

## Test e gate della fase 6

Eseguire test mirati backend e, nel frontend:

```sh
cd frontend
npm test
npm run lint
npm run build
```

Dopo rebuild, con account e dati isolati:

1. Quantita/check: ogni aumento, diminuzione, spunta e rimozione dopo grace;
   correzioni e ritorno al valore iniziale senza falsi avvisi.
2. Nome/descrizione/barcode/metadati e nome contenitore: notifiche solo per
   modifiche effettive e preferenza attivata.
3. Destinatari editor individuali/gruppi; viewer, read-only, blocco e revoca
   esclusi. Preferenze default corrette su utenti nuovi e dopo migrazione.
4. Autosave, reload persistente, errore con rollback; nessun prompt push forzato.
5. Inbox, paginazione, conteggio e lettura globale; link checklist/inventario.
6. Desktop/mobile e tastiera, stati caricamento/errore/vuoto.

I test con API simulate non certificano push reale. Safari remoto/banner/click
OS, prompt iniziale e dispositivi iOS/Android restano verifiche fisiche.
STOP dopo la PR: niente merge senza test e approvazione utente.

## Proposte non implementate

- Viewer: esclusione dagli avvisi operativi; eventuale riepilogo giornaliero
  opt-in, limitato alle risorse consultabili, solo se richiesto in futuro.
- Admin: fallimento backup dopo retry; worker fermo/coda bloccata oltre una
  soglia temporale; VAPID non valido o picco di errori push; cambi di ruolo,
  blocchi e revoche globali eseguiti da altri admin.
- Anti-spam admin: un avviso per incidente, successivo messaggio di ripristino,
  aggregazione e cooldown. Niente notifica per ogni login, retry o modifica
  ordinaria di tutti gli inventari.
