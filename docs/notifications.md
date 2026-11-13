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
contenitori; nessun utente riceve notifiche delle proprie modifiche.
Nel Profilo dei viewer viene mostrata una spiegazione, senza controlli di
preferenza o richiesta del consenso push per eventi che non possono ricevere.

| Evento | Quando | Inbox predefinita |
|---|---|---|
| `item_quantity_changed` | Qualsiasi variazione di quantita o spunta di una singola riga | Disattiva |
| `item_updated` | Creazione o eliminazione di un elemento oppure modifica effettiva dei suoi dettagli | Disattiva |
| `inventory_updated` | Modifica effettiva del contenitore, attualmente il nome | Disattiva |
| `filter_trigger_matched` | Un trigger pianificato trova elementi compatibili con un filtro | Disattiva |

Tutti gli eventi sono disattivati per inbox e push per gli utenti nuovi e
all'inizializzazione della migrazione. La migrazione a preferenze personali
elimina le vecchie preferenze; se e gia stata applicata, non viene rieseguita
e le preferenze personali gia salvate restano invariate. Il push richiede due consensi:
preferenza personale per evento e attivazione esplicita del browser.
Per ogni evento si sceglie una sola modalita: **Disattivate**, **Solo Inbox**
oppure **Inbox + Push**. Push senza Inbox non e consentito, anche via API.
L'autore della modifica e sempre escluso dai destinatari, sia inbox sia push.
Questa esclusione riguarda gli eventi di modifica: i trigger sono eventi di
sistema con `actor_id=null`, quindi anche il loro creatore può riceverli.

### Filtri generici e trigger pianificati

I filtri usano gli ID già esistenti di `filter_templates`. La rappresentazione
generica è versionata (`criteria.version=2`) e supporta insieme campi dell'elemento
e metadati. Gli endpoint `/filter-templates` e `/metadata/filters/*` mantengono
il comportamento dei filtri legacy; la nuova lista legacy non include i filtri
v2 e la lettura/modifica di un filtro v2 via API legacy restituisce 409, indicando
di usare `/filters`. Nessun criterio legacy viene riscritto durante lettura o
valutazione; anche i caratteri jolly dei filtri testuali legacy restano invariati.
Un filtro legacy invalido resta elencabile con scope `none` e
`validation_error` esplicito (stringa; `null` per un filtro valido), ma valutazione e
creazione trigger falliscono esplicitamente (422).
L'editor non deve aprire i criteri vuoti come filtro valido: mostra l'errore
e permette la cancellazione, non un salvataggio distruttivo. PATCH senza
nuovi criteri validi fallisce con 422 e mantiene il contenuto originale.

API (percorsi relativi al root path API):

* `GET /filters`, `GET /filters/{id}`, `POST /filters`,
  `PATCH /filters/{id}`, `DELETE /filters/{id}`.
* `GET /filters/fields`: catalogo `{field,label,source,field_type,definition_id?,
  operators,container_types,list_options?}`. I metadati sono limitati a quelli
  visibili tramite i contenitori; l'admin vede tutte le definizioni.
* `POST /filters/preview`: il filtro completo più `inventory_id?` e
  `timezone?` (predefinita `Europe/Rome`).
* `POST /filters/{id}/evaluate`: `{inventory_id?,timezone?}`; un filtro legacy
  legato a un contenitore non può essere valutato su un altro contenitore.
* `GET /triggers`, `GET /triggers/{id}`, `POST /triggers`,
  `PATCH /triggers/{id}`, `DELETE /triggers/{id}`.
* `POST /triggers/{id}/preview`: valuta con i permessi dell'utente corrente,
  senza generare eventi, aggiornare baseline o eseguire notifiche.
* `GET /triggers/subscriptions`: `{trigger_id,enabled}[]`.
  `PUT /triggers/{id}/subscription`: `{enabled:boolean}`.

Il filtro contiene `{name,description?,is_shared,container_type,match_mode,
conditions}`. `container_type` è `INVENTORY`, `CHECKLIST` o `null`; `match_mode`
è `all` oppure `any`. Ogni condizione contiene `{source,field,definition_id?,
operator,value?,range_from?,range_to?}`. `source` è `item` o `metadata`;
per i metadati `field` deve coincidere con la chiave della definizione.
I campi elemento sono `name`, `description`, `quantity`, `completed`,
`priority`, `barcode`, `created_at`, `modified_at`. `quantity` è disponibile
negli inventari; `completed` e `priority` nelle checklist. `completed` significa
`quantity>0`. `barcode` supporta solo `contains`, `is_null`, `is_not_null`.
Gli altri operatori provengono dal catalogo canonico dei metadati.

`value` ed estremi accettano stringhe, numeri, booleani, `null` oppure
`{relative_days:intero}` (da -36500 a 36500). Le date fisse sono ISO
`YYYY-MM-DD`; le date relative rappresentano **OGGI + X giorni di calendario**
nel fuso della valutazione, senza aritmetica approssimata su mesi/anni.
Gli estremi `between` sono inclusivi e devono essere ordinati anche dopo
la risoluzione relativa. Le date degli elementi sono confrontate come giorni
locali su timestamp UTC: i giorni DST possono durare 23/25 ore. Le date EAV
restano date di calendario. Gli operatori NULL non accettano valori;
confronti, `not_equals` e `not_contains` non corrispondono a valori assenti.
Un campo non disponibile nel contenitore è sempre falso, anche per `is_null`.
In `any` si usa l'unione delle condizioni compatibili, non l'intersezione dei
tipi dei campi. `contains` generico interpreta il testo letteralmente,
non come pattern SQL. Nessun campo o operatore permette SQL arbitrario.

Le valutazioni restituiscono
`{containers:[{id,name,type,item_ids,count}],total_count}`; sono inclusi solo
i contenitori con corrispondenze. Le risposte filtro aggiungono audit
`id,user_ins,user_mod,data_ins,data_mod`, `scope_preview`, `trigger_count`,
`can_manage`, `validation_error`. `scope_preview` è `{scope_type,summary,inventories:[{id,name,type}]}`,
limitato ai contenitori visibili/compatibili (`specific` o `none`).

Il trigger contiene `{name,filter_id,enabled,time,timezone,weekdays,
inventory_ids,notify_mode}`: `time` è `HH:MM`, fuso IANA (predefinito
`Europe/Rome`), giorni ISO da 1 lunedì a 7 domenica, contenitori `null`
per tutti quelli compatibili/modificabili dal creatore oppure elenco esplicito.
`notify_mode` è `always` o `changed`. La risposta aggiunge
`id,filter_name,scope_preview,can_manage,last_run_at,next_run_at,
last_result_count,last_container_count,last_error`. Timestamp di esecuzione
e prossima esecuzione sono UTC; `last_run_at` indica lo slot pianificato.
PATCH è parziale, con la stessa validazione della creazione. Creare un trigger
attiva la sola sottoscrizione del creatore; la quarta preferenza evento resta
disattivata. Altri destinatari devono attivare esplicitamente la sottoscrizione.

Solo proprietario/admin gestiscono filtri e trigger. Un filtro privato è
usabile esclusivamente da proprietario/admin; un filtro condiviso permette
trigger personali e sottoscrizioni a utenti con accesso **edit** ai contenitori
compatibili. I viewer non ricevono trigger. Il worker controlla nuovamente
creatore, filtro, scope e sottoscrizione; inbox e invio push ricontrollano questi
vincoli e il consenso personale. Cambiare/eliminare filtro o trigger invalida
gli eventi precedenti e le code; la perdita di compatibilità disattiva le
sottoscrizioni e i trigger non più autorizzati. Le modifiche legacy al filtro
applicano la stessa invalidazione. Le modifiche dei metadati sono rivalutate
al momento della consegna: un filtro non più valido non consegna.
La disattivazione della quarta preferenza o della sottoscrizione nasconde
anche le vecchie righe trigger, senza modificare il comportamento storico
delle altre tre categorie.

Ogni evento conserva `{filter_id,trigger_id,inventory_id,filter_name,count,
scheduled_at}` e i token interni `trigger_revision`/`filter_fingerprint`, per
impedire consegne stale dopo modifiche. Nome filtro e numero di risultati sono
snapshot immutabili, non letture dei risultati attuali. Un evento corrisponde
a un contenitore; il link push apre quel contenitore.

Il loop `notification_worker` esegue anche lo scheduler persistente: run ed
eventi vengono salvati nella stessa transazione. Vincoli unici su
`(trigger_id,scheduled_at)` e `(trigger_id,logical_date)` impediscono doppie
esecuzioni anche con worker concorrenti e dopo riavvio. Si recupera solo
l'ultimo slot nell'ultima ora; slot anteriori vengono saltati, nessuna
raffica di arretrati. Un orario locale inesistente durante DST viene saltato;
un orario ripetuto usa la prima occorrenza (`fold=0`) una sola volta.
Una modifica della pianificazione non provoca una seconda esecuzione
nello stesso giorno logico. Il primo risultato non vuoto di `changed`
notifica; poi si confrontano gli ID per contenitore, non soltanto il conteggio.
Un risultato vuoto aggiorna la baseline senza notificare.

Ogni tick valuta al massimo 100 trigger e scansiona al massimo 1000 righe,
con cursore circolare; ogni utente può creare 100 trigger e ogni trigger può
coprire al massimo 100 contenitori (anche a runtime, con errore esplicito
se uno scope dinamico cresce troppo). Le valutazioni fallite hanno run
`failed` e `last_error` sanitizzato (`not_authorized`, `invalid_filter`,
`evaluation_failed`, oppure `filter_revoked` dopo modifica incompatibile);
non vengono ripetute nello stesso slot. Una transazione DB non riuscita non
salva run/eventi parziali e può essere ritentata entro la finestra.
`tzdata` è una dipendenza esplicita per i fusi IANA nelle immagini Linux.

La migrazione `ba1c2d3e4f5a` segue `c1d2e3f4a5b6`, mantiene dati e
preferenze esistenti e aggiunge `scheduled_triggers`, `trigger_runs` e
`trigger_subscriptions`. Backup/esportazione e restore includono le tre
tabelle in ordine di dipendenza: i run ripristinati impediscono replay degli
slot già eseguiti, mentre inbox/outbox continuano a essere azzerati dal restore.
La migrazione supporta anche il bootstrap `Base.metadata.create_all` prima
dello stamp di una revisione precedente: verifica colonne, tipi, nullabilità,
chiavi e vincoli delle tabelle già presenti e non le ricrea. Uno schema
incompatibile causa un errore esplicito, non viene ignorato; l'indice mancante
del polling viene creato, un indice omonimo incompatibile viene rifiutato.

La preferenza **Creazione, eliminazione e dettagli degli elementi** include le
nuove righe e le cancellazioni.
La notifica indica il nome e la quantita iniziali, oppure lo stato iniziale
della spunta per le liste; questi valori rimangono riferiti alla creazione
anche se l'elemento viene successivamente modificato. I metadati inseriti
durante la creazione sono salvati insieme alla riga, senza una seconda
notifica di modifica; le successive modifiche ai metadati restano notificabili.
La notifica di eliminazione conserva il nome dell'elemento e apre il suo
inventario o lista, non l'elemento cancellato. Anche per essa sono richiesti
accesso corrente e preferenze personali.

La sezione usa un selettore segmentato per evento, con tre opzioni sempre
visibili, icone ed etichette: non richiede l'apertura di una tendina.
I radio nativi consentono anche la scelta con le frecce della tastiera.
La modalita selezionata viene salvata automaticamente.
Durante la richiesta i controlli sono disabilitati per evitare
scritture concorrenti. Un errore ripristina il valore precedente e mostra
esplicitamente come riprovare. A salvataggio concluso viene ripristinato il
focus perso per la disabilitazione, senza sottrarlo a un altro controllo.

Su mobile Gestione profilo mantiene le sezioni richiudibili. Da 768 px usa
tutta la larghezza disponibile e sezioni in tab, con lo stesso stile delle
Impostazioni. Le frecce sinistra/destra e Home/End navigano tra i tab.
Il cambio tab o layout non rimonta i form e conserva le sezioni aperte su mobile.
Gli utenti viewer continuano a vedere la spiegazione delle notifiche senza
controlli push.

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
La voce Notifiche e nascosta quando tutte le preferenze inbox e push sono
disattivate; riappare dopo l'attivazione di almeno una preferenza. La
disattivazione non cancella le notifiche gia ricevute.
Con notifiche non lette l'icona oscilla su desktop e mobile; l'animazione si
ferma a zero e rispetta la preferenza di sistema per ridurre il movimento.
La voce è nella sidebar desktop e nella barra di navigazione inferiore mobile;
il badge mostra solo i conteggi positivi (massimo visibile 99+), mai zero.
Su mobile il titolo Centro notifiche compare nel header comune alle altre pagine.
La inbox elenca 50 righe per volta con Carica altre, Aggiorna, lettura singola
e Segna tutte come lette. Le checkbox consentono di selezionare singole righe,
tutte le righe visibili oppure tutte le notifiche, anche non ancora caricate.
Le selezionate si possono segnare come lette o eliminare definitivamente,
con conferma prima della cancellazione. Ogni riga ha anche un cestino.
La lettura e cancellazione globali riguardano tutte le pagine autorizzate.
L'eliminazione rimuove fisicamente solo le righe inbox dell'utente corrente:
non cancella gli eventi condivisi, le notifiche degli altri o i banner gia
consegnati dal sistema. Lettura/eliminazione inbox non ritirano i banner push.
Il worker completa
evento e creazione delle righe in una sola transazione: non riproduce gli
eventi completati dopo l'eliminazione di una riga.
Se una selezione esplicita contiene una notifica inesistente, di un altro
utente o non piu accessibile, l'intera operazione viene rifiutata senza
modifiche parziali e l'interfaccia invita ad aggiornare l'elenco.
L'ordine e decrescente per data/ora dell'azione (ID come spareggio), non per
ordine di consegna del worker, e viene applicato prima della paginazione.

Contenitori non piu modificabili non vengono elencati, conteggiati o modificati
dalla lettura massiva. I link usano il tipo del contenitore autorizzato dal
backend; le route verificano nuovamente i permessi all'apertura.
La cancellazione di un item elimina i suoi precedenti eventi e le relative
notifiche/code, quindi registra un evento di eliminazione legato al contenitore,
senza riutilizzare l'ID dell'item. Le notifiche di eliminazione rimangono
disponibili anche se l'ID viene riutilizzato. La cancellazione del contenitore
elimina tutti i suoi eventi e le notifiche/code associate. Gli eventi
preesistenti vengono esclusi se la risorsa corrente e stata creata dopo l'evento.
Aprire direttamente un inventario o una lista non segna le notifiche come lette.
La freccia di una notifica non letta apre la risorsa e segna letta solo quella
notifica; un errore resta visibile con la possibilità di riprovare. Il click su
un banner push apre invece la risorsa con l'UUID evento nel link:
dopo autenticazione l'app segna come letta solo la notifica di quell'evento
appartenente all'utente corrente e aggiorna la campanella. Il parametro viene
rimosso dopo il successo; login conserva la destinazione. Account diverso,
accesso revocato o errore di rete non marcano altre notifiche e mostrano errore
con possibilita di riprovare. Il worker non accede a token o API autenticate.
Inbox + Push crea anche una riga inbox per ogni evento; se l'utente l'ha gia
eliminata, non viene ricreata dal click sul banner.
Lo stato letto riguarda la inbox, non certifica consegna o visualizzazione push.
Le righe compatte mostrano icona inventario/lista, nome, elemento e azione
(quantita con delta firmato, spunta, titolo/descrizione aggiornati), data/ora
dell'azione e pulsanti a destra per aprire inventario/lista, segnare letto o eliminare.
Il pulsante di lettura resta visibile dopo la lettura, grigio e disabilitato
con etichetta "Gia letta", mantenendo stabile il layout delle azioni.
Titolo e descrizione sono salvati nell'evento, non ricavati dal valore corrente:
una modifica successiva non riscrive il dettaglio storico. Per eventi precedenti
senza dettagli viene indicato il campo modificato; per barcode/metadati e
assegnazioni viene indicata la categoria, senza inventare valori storici.
Il payload push di sistema include i dettagli descritti sotto senza colonne
aggiuntive per i singoli dettagli.

### API

Tutti gli endpoint sono autenticati e limitati all'utente del token:

| Metodo | Percorso | Risultato |
|---|---|---|
| GET | `/notifications?limit=50&offset=0` | Inbox autorizzata con tipo/nome contenitore |
| GET | `/notifications/unread-count` | `{count}` |
| PUT | `/notifications/{id}/read` | Lettura singola |
| PUT | `/notifications/events/{event_key}/read` | Lettura dell'evento del banner, solo propria inbox |
| PUT | `/notifications/read-all` | `{updated}`, tutte le pagine autorizzate |
| POST | `/notifications/bulk` | `{action: "read" \| "delete", ids: [...]}` oppure `{action: ..., all: true}`; restituisce `{updated}` |
| DELETE | `/notifications/{id}` | Elimina definitivamente la propria riga inbox |
| GET | `/notifications/preferences` | Preferenze personali dei tre eventi |
| PUT | `/notifications/preferences/{event_type}` | `{in_app_enabled, push_enabled}`; Push richiede Inbox |

Non esistono endpoint o editor per configurazioni condivise di notifica.
Entrambi i canali hanno default `false`. Push senza Inbox e campi rimossi
vengono rifiutati con `422`, senza modificare le preferenze.

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

La successiva migrazione `c1d2e3f4a5b6` conserva preferenze, eventi, inbox,
sessioni e sottoscrizioni. Converte le preferenze solo Push in Inbox + Push,
senza creare retroattivamente righe inbox per gli eventi gia elaborati.
Elimina la colonna `include_own_actions` e aggiunge il vincolo DB che richiede
Inbox quando Push e attivo. I timestamp delle preferenze non cambiano.
Gli invii pendenti per modifiche dell'utente stesso vengono annullati dal worker;
le righe inbox gia ricevute restano storiche. Per installazioni nuove viene
supportato anche il bootstrap ORM prima delle migrazioni.

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

Il comando `python -m notification_worker --healthcheck` controlla prima
heartbeat (massimo 120 secondi) e PID, poi esegue due query DB. Non carica
outbox, VAPID o librerie di invio push. I log della sonda indicano la fase
raggiunta e, in caso di successo, il tempo impiegato. Se il controllo scade,
questo output si trova nella cronologia health di Docker, non nei normali log
del processo worker.

Lo stato `unhealthy` non riavvia da solo un container Docker Compose:
`restart: always`/`unless-stopped` agiscono quando il processo termina.
In caso di avvii ripetuti verificare contatore riavvii, exit code, OOM ed
eventuali strumenti esterni di auto-healing. Ad esempio, per il container DEV:

```sh
docker inspect --format 'status={{.State.Status}} restarts={{.RestartCount}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}' notification-worker-dev
docker inspect --format '{{range .State.Health.Log}}{{.End}} exit={{.ExitCode}} {{.Output}}{{println}}{{end}}' notification-worker-dev
docker exec notification-worker-dev python -m notification_worker --healthcheck
```

Il worker registra PID e data/ora all'avvio, il segnale ricevuto per gli
arresti ordinati e la conclusione del processo. Un `SIGKILL`/OOM non consente
di scrivere il log finale e va verificato tramite lo stato/eventi di Docker.

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
Con Web Push abilitato e percorso/contatto configurati, il backend genera
automaticamente una chiave privata P-256 al primo avvio, solo se il file non
esiste. Il file viene scritto con permessi `0600` e pubblicato atomicamente:
avvii concorrenti riutilizzano la stessa chiave, senza sovrascriverla.
Montare la directory su un volume persistente condiviso da API e worker;
il percorso configurato deve essere scrivibile alla prima generazione.
Il worker si limita a leggere la chiave: avviarlo dopo che il backend e sano
(come nei Compose del repository). Non serve generare un file di chiave pubblica.

Un PEM preesistente viene riutilizzato, anche se fornito in sola lettura.
File corrotto, cifrato, illeggibile o configurazione non valida impediscono
l'avvio del backend con push abilitato: non vengono rigenerate chiavi come
fallback. Se il file diventa non valido a runtime, l'API push risponde `503`.
Il worker non si avvia con una configurazione mancante/non valida.
L'API deriva la chiave pubblica dal PEM privato; la chiave JWT e indipendente.
Cambiare VAPID richiede rinnovo delle sottoscrizioni browser.

### Sessioni, invii e limiti

Gli endpoint `/notifications/push/config`, `/subscriptions` e `/deliveries`
gestiscono configurazione pubblica, sottoscrizioni della sessione e risultati
tecnici. Il backend ricava user/session ID dal JWT. Il POST sottoscrizione
richiede `consent: true`, endpoint HTTPS e chiavi P-256 valide.
Una sottoscrizione non viene trasferita ad altro account.

Prima di ogni tentativo si ricontrollano sessione, blocco utente, generazione,
VAPID, preferenza, esclusione dell'autore e permesso di modifica. Logout/revoca/blocco
impediscono nuovi invii; un messaggio gia affidato al provider non e ritirabile.
Eventi precedenti al consenso non producono push retroattivi.

Host consentiti: `fcm.googleapis.com`, `updates.push.services.mozilla.com`,
`web.push.apple.com`. Solo HTTPS, IP pubblici validati e DNS pinning; niente
redirect, host arbitrari o proxy ambientali.

I banner desktop/mobile mostrano il nome inventario/lista con `📦` o `☑` nel titolo,
nome item e modifica nel testo (delta quantita, spunta, titolo/descrizione,
categorie barcode/metadati). Il click apre direttamente inventario/lista,
con normale verifica login/accessi. Titolo massimo 40 caratteri e testo 500,
con ellissi per valori lunghi; l'OS puo troncare ulteriormente le anteprime.
Il titolo e generato dall'app usando il nome del contenitore: non viene
aggiunto un suffisso con il dispositivo. Eventuali nomi dispositivo presenti
nel nome del contenitore restano parte del titolo; intestazioni e ritorni
a capo aggiunti da iOS/Android non sono controllabili dall'app.

Inbox e banner usano gli stessi indicatori Unicode, visibili anche su
iOS/Android senza dipendere dal supporto a immagini personalizzate:

| Simbolo | Operazione |
|---|---|
| 🟢＋ | Creazione elemento |
| 🟡✎ | Modifica elemento o contenitore |
| 🔴✕ | Eliminazione elemento |
| 🟡↑ / 🟡↓ | Aumento / diminuzione quantita |
| 🟡☑ / 🟡☐ | Completato / non completato (casella vuota) |

Il simbolo sostituisce diciture come "Nuovo elemento"; `×2` indica la quantita
iniziale, `-1 (2 → 1)` una variazione. Forma e descrizioni accessibili nel
centro notifiche distinguono le operazioni anche senza colore. Il disegno
esatto degli emoji e la disposizione del banner dipendono dal sistema.
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
In caso di errore di attivazione il pannello permette di riprovare e indica
la fase fallita (configurazione, service worker, sottoscrizione browser o
registrazione server) e l'eventuale codice HTTP, senza mostrare chiavi o endpoint.
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
