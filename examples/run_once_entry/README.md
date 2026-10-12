# run_once_entry

La procedura di ingresso per una data extension pianificata "Run Once": event definition `EmailAudience` con
`metaData.scheduleFlowMode` = `runOnce` e `runOnceScheduleMode` = `onPublish`, e un `automationId` che non
corrisponde a nessuna automation del package, come negli export reali.

## Journey

```
SPLIT-1 "Opt-in"   Event.Optin Is true  -> UPDATE-1 "Opted in"
                   remainder            -> UPDATE-2 "Not opted in"
```

Tabelle: `DE_RO_Entry` (ingresso: `SubscriberKey`, `EmailAddress`, `Optin` Boolean che ammette null),
`DE_RO_Log` (solo scritta).

## Risposta attesa, passo per passo

1. **Copertura.** `Optin` è un campo Journey Data della tabella di ingresso, a livello di contatto. `True` ->
   UPDATE-1, `False` o null -> UPDATE-2, con la preferenza "not null" per il remainder (`False`). Entrambi i
   branch **coperti**; **1 scenario, 2 casi, 6 contatti**. Un solo CSV: `DE_RO_Entry`.
2. **Procedura.** Spec, "Entry source and procedure": la procedura dipende dalla entry source, "read from the event
   definition (type and `metaData.scheduleFlowMode`)". Riga "Data extension, Run Once": "Import every CSV, then
   activate the journey. Only rows present at activation enter; rows imported later never do (confirmed). A new
   attempt needs a new journey version and a new run identifier." La tabella dice che la procedura va in "report.md
   and the testbook". Quindi:
   - report.md nomina Run Once e la nuova versione del journey (`versione`);
   - il testbook dice che un nuovo tentativo richiede una nuova versione e un nuovo run identifier.
   Oggi nessuno dei due testi contiene "versione", e il testbook non contiene "run identifier".

## Non verificato

- "All scenarios enter together, so 'one active scenario at a time' is not offered.": qui c'è un solo scenario e
  nessun campo di attivazione (non c'è una entry query), quindi non c'è niente da osservare.
- "The entry data extension must hold only test rows when the journey is activated; report.md says so for Run Once
  entries.": la formulazione non è fissata dalla spec, quindi non è controllata.
- La frase "Importa ogni CSV, poi attiva il journey": "attiva" compare già nei testbook di oggi (attivazione dello
  scenario) e non distinguerebbe nulla.
