# default_missing_column

Un default del journey che nomina una colonna assente nella data extension di ingresso: `defaults.mobileNumber`
legge `Event."MobilePhone"`, ma `DE_DM_Entry` non ha `MobilePhone`. La forma (`defaults.mobileNumber` sui Journey
Data) è quella degli export reali.

## Journey

```
SPLIT-1 "Opt-in"   Event.Optin Is true  -> UPDATE-1 "Opted in"
                   remainder            -> UPDATE-2 "Not opted in"
```

Tabelle: `DE_DM_Entry` (ingresso da Run Once: `SubscriberKey`, `EmailAddress`, `Optin`), `DE_DM_Log` (solo
scritta). `defaults.email` legge `EmailAddress`, che esiste.

## Risposta attesa, passo per passo

1. **Copertura**: `Optin` `True` -> UPDATE-1, `False` (preferito a null) -> UPDATE-2. **1 scenario, 2 casi,
   6 contatti**, entrambi i branch **coperti**.
2. **Default.** Spec, "Honest outcomes": "A journey default (email, mobile number) that names a column the entry
   data extension lacks is reported." Il report nomina `MobilePhone`; nessuna tabella dell'export ha un campo con
   questo nome, quindi non può comparire per altri motivi.

## Non verificato

- La formulazione del warning.
- Che non ci sia un warning sul default email, che è corretto: la spec non chiede di dirlo.
