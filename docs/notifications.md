# Notifiche: sviluppo per fasi

Epic: [#38](https://github.com/NHWS-Org/home-inventory/issues/38).
Tutte le PR delle sub-issue sono destinate al branch dell'epic
`38-feature-device-notification-on-logged-device`, mai direttamente alla release
o a `main`. I branch delle fasi successive partono dal branch epic aggiornato.
Ogni fase si ferma dopo test automatici e PR, in attesa dei test e
dell'approvazione dell'utente. Solo dopo il completamento e la validazione di
tutte e sette le fasi, una PR porta il branch epic in `release/1.6.0`.

## Decisioni approvate

- Centro notifiche interno e Web Push standard/VAPID; nessun provider commerciale
  obbligatorio. Il trasporto push usa comunque i servizi dei browser/OS.
- Worker dedicato e coda persistente nello stesso database dell'applicazione,
  senza Redis/Celery nella prima versione.
- Prima versione: condivisione, attraversamento di una soglia di quantita,
  completamento di una lista da parte di un altro utente.
- Proprietario/admin gestiscono regole condivise; il destinatario deve avere
  accesso alla risorsa. Preferenze personali e consenso per browser/dispositivo
  non possono essere forzati da un amministratore.
- Centro notifiche abilitato di default per gli eventi configurati, push
  disabilitato e azioni proprie escluse. Nessuna regola rumorosa preattivata.
- Payload lock screen generico, dettagli solo dopo consenso esplicito.
- Nessuna garanzia di consegna o copertura di ogni browser/OS.
- Scadenze metadata DATE, errori backup, riepiloghi e fasce silenziose sono rinviati.

## Fasi e dipendenze

| Fase | Issue | Contenuto | Prerequisiti |
|---|---|---|---|
| 1 | [#53](https://github.com/NHWS-Org/home-inventory/issues/53) | Contratti, persistenza, migrazioni | Approvazione proposta |
| 2 | [#54](https://github.com/NHWS-Org/home-inventory/issues/54) | Outbox transazionale, worker e retry | 1 e test utente |
| 3 | [#55](https://github.com/NHWS-Org/home-inventory/issues/55) | Regole, accessi, emissione eventi | 2 e test utente |
| 4 | [#56](https://github.com/NHWS-Org/home-inventory/issues/56) | Web Push backend e sessioni | 3 e test utente |
| 5 | [#57](https://github.com/NHWS-Org/home-inventory/issues/57) | Service worker e consenso | 4 e test utente |
| 6 | [#58](https://github.com/NHWS-Org/home-inventory/issues/58) | Centro notifiche, preferenze, editor | 5 e test utente |
| 7 | [#59](https://github.com/NHWS-Org/home-inventory/issues/59) | End-to-end e verifica piattaforme | 6 e test utente |

## Fase 1: contratto e limiti

Non aggiunge endpoint, worker, invii, regole attive o interfacce. Non chiede
permessi al browser. Le tabelle nuove sono vuote finche le fasi successive non
le utilizzano:

- `notification_events`: outbox con UUID stabile, versione schema, attore,
  payload JSON, data UTC di creazione/disponibilita, stato e numero tentativi.
  UUID e contenuto identificano l'evento anche quando la valutazione viene
  ripetuta. Stati ammessi: pending, processing, completed, failed.
- `notifications`: una riga per coppia evento/utente, con data di lettura.
  Non viene salvata una copia dei nomi/contenuti delle risorse.
- `notification_preferences`: una riga per utente/tipo evento, canali e inclusione
  delle azioni proprie; campi di audit tramite `LoggingData`.

Eventi e righe inbox sono registrazioni tecniche/storiche, come le sessioni
dispositivo e gli snapshot audit: hanno timestamp propri, non `LoggingData`.
Il contratto Pydantic rifiuta tipi sconosciuti, ID non positivi, campi aggiuntivi,
coercizioni e variazioni di quantita senza un effettivo cambiamento.

| Tipo payload | Dati |
|---|---|
| inventory_shared | inventory_id, recipient_kind (user/group), recipient_id |
| item_quantity_changed | inventory_id, item_id, previous_quantity, quantity |
| checklist_completed | inventory_id |

`actor_id` e `schema_version=1` sono nell'envelope persistente. Le date nel DB
seguono la convenzione UTC senza timezone del progetto. Il payload contiene ID,
non testi privati. Non costituisce una prova di autorizzazione: i servizi futuri
devono validarlo prima del salvataggio e verificare accessi prima di invio/lettura.
Solo il contratto condiviso interpreta i tipi evento; la soglia e il destinatario
finale saranno valutati dal motore regole.

La fase 2 aggiungera claim/lease, recupero, scadenze ed errori operativi prima
di avviare un worker. Gli eventi devono essere inseriti nella stessa transazione
della modifica, senza commit autonomi e senza invii durante la richiesta.
Deduplicazione per evento/utente, anche con piu regole o gruppi.

Il backup logico include automaticamente le nuove tabelle tramite i modelli.
In questa fase non ci sono sottoscrizioni o credenziali push. Prima di abilitare
worker e invii, le fasi 2/4 devono impedire il replay di invii ripristinati e la
riattivazione di sottoscrizioni obsolete. Logout, revoca, scadenza, blocco e cambio
account devono impedire nuovi invii; quelli gia affidati al provider non sono
revocabili con certezza.

La migrazione supporta sia DB precedenti sia il bootstrap `create_all` eseguito
prima di Alembic dall'entrypoint Docker. Il downgrade elimina solo le tre nuove
tabelle (e i loro dati), non utenti, inventari o sessioni.

## Fase 4: Web Push backend e sessioni

Branch `notifications/56-web-push-backend`, PR verso il branch epic #38.
La revisione `f8a9b0c1d2e3` aggiunge `push_subscriptions` e `push_deliveries`
al precedente head unificato `e7f8a9b0c1d2`.
Questa fase non aggiunge UI, service worker o richiesta permessi al browser:
sono previsti nelle fasi 5/6. Gli invii reali desktop/iOS restano da verificare.

### Configurazione dell'installazione

Web Push e disabilitato di default. Per abilitarlo, configurare **sia API sia
worker**, mantenendo attivo il profilo Compose `notifications`:

```dotenv
WEB_PUSH_ENABLED=true
WEB_PUSH_VAPID_PRIVATE_KEY_FILE=/app/data/private_key.pem
WEB_PUSH_VAPID_SUBJECT=mailto:amministratore@example.com
```

In Dev usare il file privato `backend/.env`, caricato da entrambi i servizi.
In produzione usare shell/`.env` root: il Compose passa le tre variabili a
entrambi. Il file PEM deve essere leggibile nello stesso percorso nei due
container, sul volume persistente condiviso o tramite un mount secret dedicato.
Non inserire chiavi in `.env.dev`, repository o immagine.

Generare una coppia P-256 **una volta**, prima di abilitare gli invii. Dopo il
rebuild della nuova immagine, per il volume Dev gia esistente:

```bash
docker compose -f docker-compose-dev.yml exec backend sh -c \
  'cd /app/data && test ! -e private_key.pem && test ! -e public_key.pem && umask 077 && vapid --gen'
```

Il comando rifiuta di sovrascrivere chiavi esistenti; non stampa la chiave
privata. `public_key.pem` e pubblico; l'API deriva direttamente dal PEM privato
la `applicationServerKey` in base64url, evitando coppie incoerenti.
Per produzione adattare il comando al Compose utilizzato.
Poi configurare le variabili e ricreare API e worker.
Conservare la chiave privata con permessi restrittivi e in un backup separato
protetto. L'app non la genera, non la cambia automaticamente e non la salva nel DB.
Chiave assente/corrotta o configurazione invalida con push abilitato:
API push `503`, worker non avviabile; niente fallback o chiavi effimere.
La chiave JWT e indipendente dalla chiave VAPID.

Sostituire il PEM cambia la chiave pubblica e rende inutilizzabili le vecchie
sottoscrizioni per nuovi invii. I browser devono eliminare la vecchia
sottoscrizione e richiedere un nuovo consenso/registrazione.
Disabilitare Web Push cancella gli invii che il worker trova pendenti,
senza modificare inbox o dati applicativi.

### API e consenso

Tutti gli endpoint sono autenticati, sotto `/notifications/push`:

| Metodo e percorso | Risultato |
|---|---|
| GET `/config` | Chiave pubblica, payload generico e TTL; `503` se disabilitato/non configurato |
| POST `/subscriptions` | Registra/rinnova endpoint per la sessione JWT corrente (`201`) |
| GET `/subscriptions` | Elenco della sessione corrente, senza endpoint/chiavi |
| DELETE `/subscriptions/{id}` | Elimina la sottoscrizione della sessione corrente e la relativa coda |
| GET `/deliveries?limit=50` | Esiti tecnici dell'utente, massimo 100 righe, senza credenziali |

Il POST accetta il JSON della Push API con `endpoint`, `keys.p256dh`,
`keys.auth`, `expirationTime` opzionale e `consent: true` esplicito.
Sono validati tipo, lunghezza e curva P-256 delle chiavi. Non accetta user/session ID:
il backend li ricava dal token. I JWT legacy senza sessione tracciata richiedono
un nuovo login (`401`). Scadenza massima: scadenza della sessione, ulteriormente
limitata da `expirationTime` se presente.

La chiave hash dell'endpoint e unica globalmente. Lo stesso endpoint ripetuto
dalla stessa sessione non duplica righe o invii. Una nuova sessione dello stesso
utente cambia la generazione e cancella i vecchi invii al controllo pre-send.
Un endpoint gia associato a un altro account e rifiutato (`409`):
al cambio account il client deve fare unsubscribe nel browser e creare una
nuova sottoscrizione, non trasferire endpoint o chiavi del vecchio account.
Il limite applicativo e 100 sottoscrizioni per utente.

Le preferenze `/notifications/preferences` aggiungono `push_enabled`, **false**
di default. Serve sia consenso del browser/dispositivo sia consenso per tipo
evento. Inbox e push sono indipendenti: si puo disattivare la inbox mantenendo
push attivo. Le azioni proprie restano escluse salvo `include_own_actions`.
La fase 5 gestira il consenso browser; la fase 6 offrira l'editor preferenze.
Eventi precedenti al consenso/alla sottoscrizione non producono invii retroattivi.
Modificare regole/preferenze dopo l'evento invalida i relativi invii pendenti.

### Invii, lifecycle e sicurezza

- La valutazione regole crea la coda push nella stessa transazione della inbox,
  senza contattare provider. Il worker invia solo dopo il commit dell'evento.
  Una coppia evento/sottoscrizione produce una sola riga.
- Prima di **ogni** tentativo si rivalutano sessione attiva/non scaduta,
  utente non bloccato, account proprietario della sessione, generazione,
  chiave VAPID, consenso e azioni proprie, regole/destinatari attuali e accesso
  alla risorsa. Logout, revoca personale/globale e rotazione JWT revocano
  le sessioni e impediscono nuovi invii. La pulizia delle sessioni elimina
  sottoscrizioni e code tramite FK cascade.
- Claim e lease separati dalla outbox eventi. Il controllo e l'invio sono
  serializzati con revoca/blocco tramite lock DB (write fence su SQLite).
  L'invio gia iniziato prima della revoca puo comunque essere accettato:
  non e possibile ritirare con certezza un messaggio gia affidato al provider.
- Host ammessi esatti: `fcm.googleapis.com`,
  `updates.push.services.mozilla.com`, `web.push.apple.com`.
  HTTPS obbligatorio; niente host arbitrari, credenziali URL, porte alternative,
  redirect o proxy ambientali. Il socket usa solo IP pubblici validati,
  con DNS pinning e TLS/SNI sul nome originale: nessuna seconda risoluzione
  puo trasformare una destinazione pubblica in privata. Un nuovo servizio
  browser richiede modifica/verifica dell'allowlist, non un env permissivo.
- Cifratura standard `aes128gcm` e VAPID tramite `pywebpush`. Payload sempre
  generico: titolo `Home Inventory`, testo `Hai una nuova notifica`, percorso
  interno `/notifications` e tag UUID evento. Non contiene nomi, quantita,
  checklist o altri contenuti privati. TTL provider 300 secondi; coda massimo
  24 ore, mai oltre la scadenza dell'evento.
- `201`/`202` significa **accepted** dal push service, non visualizzata,
  consegnata al dispositivo o letta. `read_at` resta un dato della inbox.
  Endpoint `404`/`410`: eliminati insieme a chiavi e coda associata.
- `429`/`5xx`: backoff 30/60/120/240 secondi, al massimo 5 tentativi;
  `Retry-After` numerico rispettato fino a un'ora. Altre risposte: failed,
  senza retry. Redirect non seguiti. Esiti conservati nell'API tecnica.
- Timeout, errori di rete/DB e crash dopo claim possono avvenire dopo
  l'accettazione: stato **uncertain**, mai replay automatico del tentativo
  ambiguo. Dopo lease scaduta la coda non reinvia alla cieca.
  La deduplicazione lato service worker tramite tag arrivera nella fase 5.
- I log contengono solo ID tecnici, stato e classe errore, mai endpoint,
  chiavi, corpo provider o testo di eccezioni di trasporto.

### Backup e restore

Gli archivi `.hibackup` e gli snapshot DB per confronto escludono le tabelle
transitorie `push_subscriptions` e `push_deliveries`.
Il restore applicativo svuota sempre entrambe le tabelle prima di
ripristinare altri dati, anche preservando l'admin e anche se un archivio
importato contiene righe push. Non ripristina consenso, credenziali endpoint
o code esterne. Le vecchie outbox notifiche continuano a essere scartate.
Se un archivio importato contiene comunque dati push, il confronto
maschera endpoint, p256dh e auth.

Per un **restore fisico** SQLite/PostgreSQL/MySQL o rollback del volume:
fermare API e worker, ripristinare, applicare le migrazioni e **prima di
riavviare** eseguire nel medesimo ambiente/configurazione:

```bash
python -m notification_worker --reset-push
```

Il comando elimina solo sottoscrizioni e invii push, non inbox o inventari.
La vecchia outbox eventi puo ricreare inbox ma non invii esterni senza
sottoscrizioni. Non riavviare worker su una copia fisica senza questo reset.
Ricopiare un DB/volume senza seguire la procedura non e un restore applicativo
e non offre la protezione automatica anti-replay.

### Test pre-merge e stop

Test automatici con trasporto mock, DB SQLite con FK, migrazione
upgrade/downgrade e bootstrap: consenso, sessioni reali JWT, deduplica,
account swap, accessi/regole/preferenze revocati, scadenze, endpoint morti,
retry/lease/crash, cifratura VAPID, SSRF/DNS pinning e restore senza replay.

Verifiche utente di questa fase: rebuild/migrazioni, worker healthy con push
disabilitato e poi con PEM valido, `GET /notifications/push/config`
autenticato restituisce solo la chiave pubblica; inbox e login precedenti
restano funzionanti. Un vero endpoint desktop/iOS potra essere registrato
da client Push API gia disponibili, ma nessun client nuovo e incluso qui.
I test reali di consenso/display/click richiedono HTTPS e un browser reale;
la loro riuscita **non** e certificata dai mock. La fase 4 e completata.

## Fase 6: inbox, preferenze e regole

Branch `notifications/58-inbox-preferences-rule-editor`, PR verso il solo epic.
La campanella apre **Centro notifiche** e mostra il numero di notifiche non
lette accessibili all'utente. Il conteggio si aggiorna ogni 30 secondi, al
ritorno sulla finestra e dopo le operazioni di lettura; un errore non viene
mostrato come zero. La pagina elenca 50 righe per volta, con **Carica altre**,
**Aggiorna**, lettura singola e **Segna tutte come lette**. Il comando globale
riguarda tutte le pagine, non solo quelle caricate.

Le notifiche di contenitori non piu accessibili non vengono elencate,
conteggiate o modificate dalla lettura massiva. I link usano il tipo del
contenitore autorizzato dal backend, anche per condivisioni di checklist;
le route applicative verificano nuovamente i permessi all'apertura.
Lettura inbox, accettazione provider e visualizzazione push sono dati diversi:
aprire il contenitore non afferma che il provider abbia consegnato un push.

Nel **Profilo**, le preferenze per ciascun evento controllano inbox, push e
inclusione delle proprie azioni. Inbox predefinita attiva, push e azioni proprie
disattivati. La sezione compatta salva automaticamente ogni tocco su un parametro;
durante il salvataggio i controlli sono disabilitati per evitare richieste
concorrenti. In caso di errore viene ripristinato il valore precedente e
mostrato un messaggio per riprovare. Abilitare
push qui non richiede permessi al browser e non crea sottoscrizioni.

In ciascun inventario/checklist, **Regole notifiche** e visibile solo a
proprietario o admin. L'editor guida evento, soglia (solo quantita),
destinatari autorizzati, attivazione e riepilogo, con creazione/modifica/eliminazione.
Il canale segue le preferenze personali di ogni destinatario: il contratto
regole non impone un canale e non forza il consenso altrui. Il link al Profilo
permette di configurare i propri canali. Non vengono create regole automatiche.

Nuove API autenticate:

- `GET /notifications/unread-count`: `{count}`, solo notifiche accessibili.
- `PUT /notifications/read-all`: `{updated}`, sola inbox del chiamante.
- `GET /notifications/rules/{inventory_id}/recipients`: opzioni utenti/gruppi
  autorizzate, riservate al gestore del contenitore.
- La inbox include `inventory_type` e `inventory_name` dal contenitore
  autorizzato, senza affidare al client la decisione sui permessi.

### Validazione prima del merge della fase 6

Eseguire test backend mirati, `cd frontend && npm test`, lint e build.
La validazione browser con API in-memory verifica la UI, non consegna push.
Dopo rebuild dei contenitori verificare con dati di prova isolati:

1. Campanella con zero/non-zero, inbox vuota/caricamento/errore e paginazione.
2. Lettura singola e globale, aggiornamento conteggio e persistenza al reload.
3. Accesso revocato e account diverso: nessuna esposizione o lettura delle
   notifiche altrui; link inventario e checklist corretti dopo login.
4. Preferenze salvate automaticamente a ogni tocco e persistenti al reload;
   errore con ripristino del valore precedente, nessun prompt push forzato.
5. Editor proprietario/admin: creazione, modifica, eliminazione, soglia valida,
   destinatari limitati agli autorizzati; assenza editor per altri utenti.
6. Layout desktop/mobile, tastiera, nomi accessibili e feedback di errore.

La fase 5 e stata integrata dopo approvazione esplicita; ricezione remota/click
OS, prompt iniziale e dispositivi iOS/Android restano da validare realmente.
STOP dopo la PR della fase 6: niente merge senza test/approvazione utente.

## Fase 5: service worker e consenso browser

Branch `notifications/57-service-worker-consent`, PR verso il branch epic #38.
Questa fase aggiunge il consenso per browser nella pagina Profilo e il client
Web Push, senza attivare preferenze per tipo di evento o aggiungere l'inbox
frontend (fase 6).

`frontend/public/push-sw.js` e intenzionalmente minimo: non registra un handler
`fetch`, non usa Cache Storage e non legge API o dati autenticati. Mostra payload
generici, usa un tag per la deduplicazione del browser e accetta solo
destinazioni di notifica same-origin; URL esterni o malformati tornano alla home.
Il percorso push predefinito e `/notifications`, route protetta che conserva la
destinazione nel login e mostra la inbox dalla fase 6.

In **Profilo > Gestione profilo**, il pannello espone stati distinti per
supporto browser, HTTPS, installazione iOS, versione minima iOS, permesso
negato, servizio disabilitato, consenso mancante, sottoscrizione scaduta,
attiva o errore. La richiesta permessi parte solo dal pulsante di attivazione,
prima di qualunque chiamata asincrona. Attivazione e disattivazione riguardano
solo il browser corrente e la sessione autenticata; l'API non riceve identita
utente/sessione dal client. Logout, cambio account, revoca della sessione
corrente e revoca globale provano a cancellare prima il record server e poi
annullano la sottoscrizione locale. Un errore di cleanup al logout viene
registrato, ma non impedisce di chiudere la sessione.

Quando cambia la chiave VAPID o la sottoscrizione browser/server e scaduta,
il client elimina l'eventuale record server precedente prima della nuova
registrazione. La UI non permette di abilitare se l'installazione ha Web Push
disabilitato o il browser nega il permesso. Il pulsante di prova mostra una
notifica **locale** tramite il service worker: non invia al provider e non
certifica la consegna push.

Per iOS/iPadOS serve 16.4 o successivo: aprire il sito in Safari, usare
**Condividi > Aggiungi alla schermata Home**, aprire l'icona installata e
accettare il permesso con il pulsante nel profilo. Desktop e iOS richiedono
HTTPS; `localhost` e ammesso per lo sviluppo. Le notifiche di sistema dipendono
anche dalle impostazioni e dalle modalita Focus del dispositivo.

### Test e validazione fase 5

Test automatici frontend (nessun permesso reale o provider):

```bash
cd frontend
npm test
npm run lint
npm run build
```

Prima dell'integrazione verificare anche manualmente su almeno un browser
desktop e, se disponibile, iOS/iPadOS:

1. In Profilo verificare stato iniziale e attivare dal gesto esplicito; accettare
   il permesso e controllare che lo stato diventi attivo.
2. Usare **Mostra notifica di prova**; verificare visualizzazione e click. Il
   test e locale e non attesta un invio dal backend.
3. Disattivare, ricaricare e verificare che la sottoscrizione non risulti attiva.
4. Verificare logout e cambio account: il browser non deve conservare una
   sottoscrizione collegata all'account precedente.
5. In iOS/iPadOS provare solo da app aggiunta alla schermata Home. Verificare
   separatamente un vero invio dal backend dopo il consenso, senza includere
   contenuti privati nel payload.
6. Verificare che il worker non intercetti fetch/API e che un URL di click
   esterno non lasci il dominio.

I test mock non sostituiscono la verifica utente desktop/iOS. Non integrare
questa PR in release/main finche tali verifiche non sono confermate.

## Fase 3: regole, destinatari ed eventi

L'integrazione di `release/1.6.0` nel branch della fase 4 conserva le migrazioni
notifiche e sicurezza: la revisione merge `e7f8a9b0c1d2` unifica
`c4d5e6f7a8b9` e `d6e7f8a9b0c1`. Eseguire `alembic upgrade head` anche
su DB gia aggiornati a una delle due revisioni.
In Compose Dev backend e worker condividono `backenddata:/app/data` e la
gerarchia `.env.dev`, poi l'opzionale `backend/.env`; il codice proviene
dall'immagine e richiede rebuild. I file `.env` privati non sono versionati.

Branch `notifications/55-rules-events`, PR verso il branch epic #38.
Questa fase abilita solo la inbox nel database e API autenticate, non UI o push.
Nessuna regola viene creata automaticamente: senza configurazione non vengono
emessi eventi. Il worker ora registra `Notification rules enabled: database
inbox only, no external sends` invece del warning della fase 2.

La migrazione `c4d5e6f7a8b9` aggiunge `notification_rules`, con audit
`LoggingData`, FK al contenitore e vincoli sul tipo evento/soglia.

- Solo proprietario/admin possono leggere o modificare le regole del contenitore.
  Essere moderatore condiviso non basta. I viewer gestiscono le proprie
  preferenze e leggono solo la propria inbox.
- Destinatari: owner, participants (proprietario + condivisioni esplicite
  utenti/gruppi, non tutti gli admin), user/group selezionati, event_recipient
  per la nuova condivisione. I gruppi selezionati devono essere condivisi con
  il contenitore; ogni utente finale deve avere ancora accesso alla risorsa.
- I membri dei gruppi e gli accessi vengono rivalutati all'elaborazione.
  Utenti bloccati, eliminati o senza accesso non ricevono righe inbox.
  I controlli di accesso riusano `can_access_inventory`.
- Una coppia evento/utente produce al massimo una riga anche con piu regole,
  gruppi sovrapposti o retry. Preferenze mancanti: inbox attiva, azioni proprie
  escluse. Le azioni proprie si includono solo con consenso personale.
- Quantita: solo INVENTORY, soglia intera; evento corrispondente quando
  `previous_quantity >= threshold > quantity`. Altri cali sotto soglia non
  avvisano. Le correzioni accorpabili dalla cronologia (stesso item, stesso
  utente, sole quantita) condividono un unico evento pendente con variazione
  netta e scadenza mobile: 45 secondi dall'ultima modifica effettiva.
  Il valore e definito solo in `backend/quantity_changes.py` e importato da
  cronologia, notifiche e annullamento scarico delle assegnazioni.
  Tornare al valore iniziale entro la finestra elimina l'evento pendente,
  come la versione audit; anche un rimbalzo sopra soglia prima della scadenza
  non produce un falso allarme. Un no-op non prolunga la finestra.
  Dopo recupero almeno alla soglia stabilizzato per la finestra, un nuovo
  attraversamento avvisa. Utenti diversi e versioni non accorpabili restano
  eventi separati, come nella cronologia. Eventi gia elaborati non si ritirano.
- Completamento: solo CHECKLIST, transizione di una riga da non spuntata a
  spuntata quando tutte le altre righe sono gia spuntate. Una lista vuota,
  creazioni/cancellazioni righe e aggiornamenti senza cambiamenti non generano
  completamento. Anche questo evento attende la stessa finestra di quantita:
  togliere una spunta prima della scadenza annulla il completamento pendente;
  ricompletare la lista avvia una nuova finestra.
- Aggiornamento quantita e assegnazioni (scarico/ripristino stock) emettono
  eventi coerenti con l'accorpamento delle versioni audit, nella transazione della
  modifica. Anche il rollback di una versione di un item esistente passa da
  questo punto comune. Spostamenti tra contenitori e ricreazioni non vengono
  interpretati come attraversamenti della soglia nel nuovo contenitore.
- Le modifiche di righe checklist sono serializzate sul contenitore per evitare
  doppi completamenti simultanei; testato con due sessioni SQLite file-backed.
- Una regola disabilitata/eliminata o modificata dopo l'evento non elabora
  quell'evento gia in coda; nessuna nuova regola retroagisce sullo storico.
- La inbox espone ID e dati del contratto, non nomi privati memorizzati.
  Accesso rivalutato anche in lettura e marcatura letta; una risorsa non piu
  accessibile sparisce dalla risposta. Paginazione applicata ai soli risultati
  autorizzati, con batch DB limitati.
- Il restore svuota anche le regole, non solo inbox/outbox, senza importare
  quelle del backup: richiede riconfigurazione esplicita, senza invii accidentali
  o destinatari non piu validi.

### Monitoraggio worker

Entrambi i Compose eseguono `python -m notification_worker --healthcheck`
ogni 10 secondi, con timeout 5 secondi, 30 secondi di tolleranza iniziale e
3 fallimenti prima dello stato unhealthy. Non e un controllo HTTP dell'API:
verifica PID vivo, heartbeat del ciclo di lavoro aggiornato da non oltre
120 secondi e query sulla tabella outbox. L'heartbeat e locale al container,
non condiviso tra repliche; viene scritto atomicamente dopo ogni iterazione
completata e rimosso all'arresto regolare. La coda vuota e uno stato sano.
Un worker bloccato non aggiorna l'heartbeat. Il controllo non richiede una
coda vuota e non misura la consegna push; Docker segnala unhealthy ma non
riavvia automaticamente un processo ancora vivo per il solo healthcheck.

Nei log sono presenti avvio, ID ed esito delle elaborazioni e codici/classi
degli errori, senza payload o dati privati. `completed` significa regole
valutate: possono essere create zero notifiche per preferenze o autorizzazioni.
`python -m notification_worker --status` mostra i conteggi della coda.
Per applicare l'healthcheck ricreare il servizio worker; in produzione serve
anche un'immagine contenente il nuovo comando, non una vecchia `latest`.

### API fase 3

Percorsi relativi alla base API (dietro nginx: `/api`):

| Metodo | Percorso | Scopo |
|---|---|---|
| GET / POST | `/notifications/rules/{inventory_id}` | Elenco / creazione regole |
| PUT / DELETE | `/notifications/rules/{inventory_id}/{rule_id}` | Modifica completa / eliminazione |
| GET | `/notifications/preferences` | Preferenze personali con default |
| PUT | `/notifications/preferences/{event_type}` | Consenso inbox e azioni proprie |
| GET | `/notifications?limit=50&offset=0` | Inbox personale autorizzata |
| PUT | `/notifications/{notification_id}/read` | Segna letta una propria notifica accessibile |

Il permesso push non e esposto o attivato da queste API. Per il momento
l'amministrazione delle regole usa Swagger, in attesa dell'editor della fase 6.

### Test manuale fase 3 (desktop e iOS)

Smoke test automatico contro l'istanza avviata (API reali esposte da Swagger):

```sh
export NOTIFICATION_TEST_USERNAME=admin
read -rs NOTIFICATION_TEST_PASSWORD
export NOTIFICATION_TEST_PASSWORD
backend/.venv/bin/python backend/.test/notification_live.py --api-url http://localhost:3000/api
unset NOTIFICATION_TEST_PASSWORD NOTIFICATION_TEST_USERNAME
```

Il comando `read` attende la password senza mostrarla (shell bash/zsh).
Lo script e opt-in, non entra nella discovery pytest e richiede il worker attivo.
Crea tre utenti temporanei con password casuali, un inventario e una checklist;
verifica soglie/riarmo, azioni proprie, preferenze, regole CRUD, sharing,
revoca, lettura e completamento. I timeout derivano dalla stessa costante di
grace: finestra + 15 secondi per la consegna, finestra + 4 per i casi senza
notifiche. Include ritorno al valore iniziale e annullamento completamento;
il test completo dura diversi minuti per verificare il tempo reale senza
abbreviare la finestra. Ripulisce le fixture anche
in caso di errore e verifica la rimozione; non modifica le preferenze degli
account esistenti. Restano le normali tracce audit/outbox e la sessione admin
di test revocata al termine. Non esegue restore distruttivi, test browser o push.

1. Backup preventivo e branch fase 3; ricostruire usando Compose Up da VS Code
   con `COMPOSE_PROFILES=notifications` nel file `.env`, oppure:

   ```sh
   docker compose -f docker-compose-dev.yml --profile notifications up --build -d
   ```

2. Verificare migrazione a `c4d5e6f7a8b9` e nuovo messaggio del worker.
3. Aprire `http://localhost:3000/api/docs` sul desktop, oppure l'indirizzo LAN
   del computer su iOS. In **Authorize** fare login con le credenziali usuali.
   Il worker in fase 3 non richiede HTTPS perche non usa ancora il push.
4. Su un inventario di prova di cui si e proprietari (ID dalla URL), usare
   POST `/notifications/rules/{inventory_id}`:

   ```json
   {
     "event_type": "item_quantity_changed",
     "threshold": 3,
     "recipients": [{"kind": "owner"}],
     "enabled": true
   }
   ```

5. Per provare con lo stesso account, PUT
   `/notifications/preferences/item_quantity_changed`:

   ```json
   {"in_app_enabled": true, "include_own_actions": true}
   ```

6. Usare un articolo inizialmente a 5 (oppure portarlo a 5 e attendere la
   finestra), poi portarlo a 2. Prima di 45 secondi non deve esserci una nuova
   notifica; dopo 45 secondi dall'ultima modifica, piu il polling worker,
   GET `/notifications` deve contenere un evento con `5 -> 2`.
   Portarla a 1: non deve aggiungere un avviso. Portarla a 5, attendere oltre
   45 secondi, poi a 2 e attendere di nuovo: deve comparire un secondo avviso.
   Su un altro articolo inizialmente a 5, fare 5 -> 2 -> 5 entro la finestra:
   dopo la scadenza non deve esserci una notifica ne una versione audit residua.
   Ripetere senza cambiamenti: nessun duplicato.
7. PUT `/notifications/{id}/read` deve valorizzare `read_at`. Disattivare la
   preferenza inbox e ripetere il ciclo: nessuna nuova notifica.
8. Per condivisioni, creare una regola con event_type `inventory_shared`,
   threshold `null`, recipients `[{"kind":"event_recipient"}]`; condividere
   con un altro account. La inbox di quell'account riceve l'evento, non quella
   di un estraneo; ripetere una condivisione gia esistente non genera duplicati.
9. Per una checklist di prova, creare regola `checklist_completed`, threshold
   `null`, recipients `[{"kind":"owner"}]`; spuntare tutte le righe con un altro
   account autorizzato. Avviso solo dopo la finestra dall'ultima spunta.
   Togliere una spunta prima della scadenza deve annullare l'avviso pendente.
   Ricompletare e attendere abilita un nuovo avviso; un no-op no.
10. Revocare accesso a un destinatario: le vecchie notifiche relative alla
    risorsa non devono piu comparire; un estraneo non puo leggerle per ID.
11. Verificare login, sessioni profilo e backup/ripristino 1.5.0 come regressione.
    Il restore elimina le regole di prova; nessun evento del backup viene riprodotto.

Nessuna campanella o notifica OS e attesa: arriveranno nelle fasi successive.
Non avanzare alla fase 4 e non effettuare merge prima della conferma utente.
PostgreSQL/MySQL: compilazione DDL verificata; test runtime e concorrenza non
certificati in questo ambiente.

## Fase 2: outbox e worker

Branch: `notifications/54-outbox-worker`, PR verso il branch epic #38.
Nessuna emissione dalle route, regola, nuova UI o notifica push in questa fase.

- `enqueue_event(db, payload, actor_id=...)` aggiunge un evento validato alla
  sessione del chiamante senza flush o commit autonomo. La chiave evento e un
  UUID riutilizzabile per identificare duplicati; reinserirla causa un errore
  di unicita e richiede il rollback del chiamante, non un successo fittizio.
- Claim atomico tramite UPDATE condizionale; lease con token univoco di 60
  secondi, recupero dopo crash e fencing dei worker obsoleti. Sono ammesse
  piu istanze, ma solo una elabora un evento.
- Elaborazione e completamento nella stessa transazione DB; un errore annulla
  tutti gli effetti del gestore. Il gestore non deve fare commit/rollback,
  chiamate di rete o invii esterni: i futuri invii richiederanno record di
  consegna persistenti separati. La garanzia riguarda gli effetti DB, non
  l'exactly-once di un provider esterno.
- Errori temporanei dichiarati e OperationalError DB: massimo 5 tentativi,
  backoff di 30/60/120/240 secondi. Errori non recuperabili, payload/versioni
  non validi, tentativi esauriti o eventi scaduti diventano `failed`.
- Gli eventi creati dal servizio scadono dopo 7 giorni. I record precedenti con
  scadenza NULL rimangono compatibili. Errori registrati come codici e classe,
  mai con payload o testi dell'eccezione.
- La migrazione `b2c3d4e5f6a7` aggiunge lease, scadenza e ultimo errore,
  rispettando il bootstrap create_all e consentendo downgrade.
- Il restore svuota inbox/outbox esistenti, anche dell'admin preservato, e non
  importa gli eventi del backup: nessun replay dopo ripristino. Se il restore
  fallisce, il rollback preserva la coda precedente.

Il processo worker e separato dall'API e da APScheduler: nessuna istanza
duplicata causata da uvicorn reload. Il profilo Compose `notifications` e opt-in
e aspetta il backend healthy prima di partire; il worker non applica migrazioni.
Per produzione serve un'immagine backend costruita da questa fase, non una
vecchia immagine `latest` priva del modulo.

**Comportamento della sola fase 2 (superato dalla fase 3):** il gestore regole sara introdotto nella fase 3.
Ora il worker resta in attesa con coda vuota; un evento inserito manualmente
viene registrato come errore temporaneo, ritentato e infine fallisce
esplicitamente. Non viene marcato completato senza elaborazione.

### Test manuali fase 2

Con backup preventivo, usare il branch fase 2 e avviare:

```sh
docker compose -f docker-compose-dev.yml --profile notifications up --build -d
docker compose -f docker-compose-dev.yml logs --tail=80 notification-worker
docker compose -f docker-compose-dev.yml exec notification-worker python -m notification_worker --status
```

Atteso: migrazione completata dal backend, worker attivo e avviso esplicito
che le regole non sono ancora abilitate, coda vuota salvo eventi sintetici.
Verificare desktop/iOS: login, modifica quantita, liste, sessioni profilo,
backup e restore da 1.5.0. Nessuna differenza visiva o richiesta permessi.
Riavviare solo il worker e controllare che l'app rimanga funzionante:

```sh
docker compose -f docker-compose-dev.yml restart notification-worker
```

I test automatici simulano claim simultanei su SQLite file-backed, doppia
elaborazione, crash/lease scaduta, fencing, rollback degli effetti, retry
limitati, scadenza, duplicati e restore. Il DDL viene compilato anche per
PostgreSQL/MySQL; non equivale a test runtime di concorrenza su questi motori.
Fermarsi prima della fase 3 per i test e l'approvazione dell'utente.

## Verifica e stop dopo la fase 1

Test automatici:

```sh
cd backend
.venv/bin/python -m pytest .test/test_notification_foundations.py -q
```

In ambiente di test, con backup preventivo:

1. Usare il branch della PR fase 1 e ricostruire il backend.
2. Controllare che l'avvio completi il bootstrap e `alembic upgrade head`.
3. Desktop: login, apertura inventari/liste, modifica quantita, sessioni profilo.
4. iOS: stessi controlli nel browser e nella Home Screen app, se installata.
5. Atteso: comportamento identico a prima, nessuna richiesta permessi/notifica.

Il test qui e di regressione: la UI delle notifiche arrivera nelle fasi 5/6.
Non avanzare alla fase 2 finche l'utente non conferma questi controlli.

## Matrice piattaforme per le fasi push

- Desktop: test reali sui browser disponibili, piu test automatizzati Chromium
  e WebKit dove installabili; WebKit automatizzato non certifica Safari/iOS.
- iOS/iPadOS: dispositivo reale, HTTPS, versione 16.4+ e aggiunta alla Home
  Screen. Richiesta permesso solo dopo un gesto dell'utente.
- Android: automazione Chromium per logica UI, poi emulatore con servizi Google
  se disponibile. Un browser emulato non certifica consegna su dispositivo
  fisico: indicare sempre il risultato come non verificato senza tester reale.
- Tutti: permesso negato, browser non supportato, HTTP non sicuro, offline,
  sessione revocata/scaduta, cambio account, duplicati e click senza accesso.

Fonti: [WebKit iOS Web Push](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/),
[MDN Push API](https://developer.mozilla.org/en-US/docs/Web/API/Push_API).
