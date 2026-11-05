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

## Fase 3: regole, destinatari ed eventi

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
  avvisano. Dopo recupero almeno alla soglia, un nuovo attraversamento avvisa.
- Completamento: solo CHECKLIST, transizione di una riga da non spuntata a
  spuntata quando tutte le altre righe sono gia spuntate. Una lista vuota,
  creazioni/cancellazioni righe e aggiornamenti senza cambiamenti non generano
  completamento. Togliere una spunta riabilita una futura transizione.
- Aggiornamento quantita e assegnazioni (scarico/ripristino stock) emettono
  eventi prima dell'accorpamento delle versioni audit, nella transazione della
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

6. Dalla normale interfaccia portare una quantita a 5, poi a 2. Dopo alcuni
   secondi GET `/notifications` deve contenere un evento con `5 -> 2`.
   Portarla a 1: non deve aggiungere un avviso. Portarla a 5 e poi a 2:
   deve comparire un secondo avviso. Ripetere senza cambiamenti: nessun duplicato.
7. PUT `/notifications/{id}/read` deve valorizzare `read_at`. Disattivare la
   preferenza inbox e ripetere il ciclo: nessuna nuova notifica.
8. Per condivisioni, creare una regola con event_type `inventory_shared`,
   threshold `null`, recipients `[{"kind":"event_recipient"}]`; condividere
   con un altro account. La inbox di quell'account riceve l'evento, non quella
   di un estraneo; ripetere una condivisione gia esistente non genera duplicati.
9. Per una checklist di prova, creare regola `checklist_completed`, threshold
   `null`, recipients `[{"kind":"owner"}]`; spuntare tutte le righe con un altro
   account autorizzato. Avviso solo all'ultima spunta. Togliere/rimettere una
   spunta abilita un nuovo avviso; la stessa azione senza cambiamento no.
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
