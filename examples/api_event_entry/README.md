# api_event_entry

Un journey che entra da un **API event**: trigger ed event definition di tipo `APIEvent`, legati alla data extension
che contiene lo schema del payload. Forma inventata (nessun export reale a disposizione) sul modello degli altri event
definition: `eventDefinitionKey` `APIEvent-<guid>`, `arguments.serializedObjectType` 11, nessuna pianificazione.

## Journey

```
SPLIT-1 "Quantity"   Event.Quantity GreaterThan 5  -> UPDATE-1 "Bulk order"
                     remainder                      -> UPDATE-2 "Small order"
```

Tabelle: `DE_AP_Event` (la data extension dell'evento: `SubscriberKey`, `EmailAddress`, `Quantity` Number, ammette
null), `DE_AP_Log` (solo scritta).

## Risposta attesa, passo per passo

1. **Copertura.** `Quantity` è Journey Data della data extension dell'evento, a livello di contatto. Intervalli
   definiti dalla condizione: (5, +inf) e (-inf, 5]. Spec: "Coverage values are chosen strictly inside the ranges the
   conditions define, never on a bound" e "prefers ... not null". Quindi un valore > 5 per UPDATE-1 e un valore non
   vuoto < 5 per UPDATE-2 (mai 5). **1 scenario, 2 casi, 6 contatti**, entrambi i branch **coperti**. La copertura non
   dipende dalla entry source.
2. **Procedura.** Spec, "Entry source and procedure", riga "CloudPages form, API event or any other": "Not driven by
   a CSV import. The team tests a copy of the journey whose entry source is a data extension with the same columns
   (confirmed); the report says so, and the entry CSV is for that data extension." Quindi report.md e testbook parlano
   di una **copia** del journey e report.md nomina l'API event (si accetta "API event" o "APIEvent"). Il CSV è uno:
   `DE_AP_Event`, la data extension con le stesse colonne usata dalla copia.
3. **Cosa non deve dire.** "Not driven by a CSV import": la procedura Run Once ("le righe importate dopo non entrano
   mai") non compare.

## Non verificato

- Il resto della formulazione (come il report spiega perché l'import del CSV non fa entrare nessuno nel journey
  originale).
- I valori esatti di `Quantity` (la spec fissa solo l'intervallo).
