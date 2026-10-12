# cloudpages_entry

Un journey che entra da un form CloudPages (Smart Capture): trigger ed event definition di tipo
`CloudPagesSmartCaptureSubmissionEvent`, legati alla data extension in cui il form scrive. Package Manager segnala
nelle `issues` del journey `UNSUPPORTED_FUNCTIONALITY` / `JOURNEY_UNSUPPORTED_ENTRY`, come nell'export reale da cui
è presa la forma.

## Journey

```
SPLIT-1 "Consent"   Event.Consent Is true  -> UPDATE-1 "Consent given"
                    remainder              -> UPDATE-2 "No consent"
```

Tabelle: `DE_CP_Submissions` (la data extension del form e dell'evento: `SubscriberKey`, `FirstName`, `Email`,
`Consent` Boolean), `DE_CP_Log` (solo scritta). Il default email del journey legge `Event."Email"`, colonna che
esiste.

## Risposta attesa, passo per passo

1. **Procedura.** Spec, "Entry source and procedure", riga "CloudPages form, API event or any other": "Not driven by
   a CSV import. The team tests a copy of the journey whose entry source is a data extension with the same columns
   (confirmed); the report says so, and the entry CSV is for that data extension." Quindi il report parla di una
   copia del journey (`copia`) e nomina l'entry source CloudPages.
2. **CSV di ingresso.** Il CSV resta quello della data extension dell'evento, `DE_CP_Submissions`, da importare
   nella data extension con le stesse colonne usata dalla copia: un solo CSV, livello `contact`.
3. **Copertura.** `Consent` è un campo Journey Data della data extension dell'evento. `True` -> UPDATE-1; `False`
   (preferito a null) -> UPDATE-2. **1 scenario, 2 casi, 6 contatti**, entrambi i branch **coperti**. La
   copertura non dipende dalla entry source: la copia del journey ha le stesse attività.
4. **Issue di Package Manager.** "Package Manager `issues` of level warning or error are listed in the report":
   l'issue `WARNING` del journey compare nel report (`JOURNEY_UNSUPPORTED_ENTRY` o il suo tipo).

## Non verificato

- Come il report spiega che l'import del CSV non fa entrare nessuno nel journey originale: la formulazione è libera.
- Il nome con cui il report indica l'entry source: si accetta "CloudPages", "Cloud Pages" o "Smart Capture".
