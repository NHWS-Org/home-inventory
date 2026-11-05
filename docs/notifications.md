# Notifiche: sviluppo per fasi

Epic: [#38](https://github.com/NHWS-Org/home-inventory/issues/38).
Tutte le PR sono destinate a `release/1.6.0`, mai direttamente a `main`.
Ogni fase si ferma dopo test automatici e PR, in attesa dei test e
dell'approvazione dell'utente. Il branch iniziale della feature rimane intatto.

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
