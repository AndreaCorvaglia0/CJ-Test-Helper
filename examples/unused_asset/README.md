# unused_asset

Due asset nell'export che nessuna attività del journey usa: un'immagine senza `fileProperties` e una vecchia email
il cui HTML punta a `{{mcpm#/entities/assets/900911/data/fileProperties/publishedURL}}`, un path che l'immagine non
ha. Negli export reali riferimenti di questo tipo, in asset non usati, producevano molti warning sugli asset che
coprivano quelli importanti.

## Journey

```
SPLIT-1 "Opt-in"   Event.Optin Is true  -> UPDATE-1 "Opted in"
                   remainder            -> UPDATE-2 "Not opted in"
```

Tabelle: `DE_UA_Entry` (ingresso da Run Once: `SubscriberKey`, `EmailAddress`, `Optin`), `DE_UA_Log` (solo
scritta). Asset: `900911` "EX_Unused_Banner.png" (immagine), `900912` "Old Newsletter" (email). Nessuna attività
EMAILV2 nel journey.

## Risposta attesa, passo per passo

1. **Copertura**: `Optin` `True` -> UPDATE-1, `False` (preferito a null) -> UPDATE-2. **1 scenario, 2 casi,
   6 contatti**, entrambi i branch **coperti**.
2. **Nessun warning sugli asset non usati.** Spec, "Honest outcomes": "Warnings about assets the journey does not
   use are dropped." Il riferimento non risolto sta in un asset non usato: né i warning né il report nominano
   l'immagine (`900911`, `EX_Unused_Banner`) o il path `publishedURL`.

## Non verificato

- Un asset non usato con una issue di Package Manager di livello warning: la regola "Package Manager `issues` of
  level warning or error are listed in the report" e la regola sugli asset non usati qui si contraddicono, quindi
  l'esempio non ne ha.
