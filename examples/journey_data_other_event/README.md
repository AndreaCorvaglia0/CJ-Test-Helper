# journey_data_other_event

Una condizione Journey Data che nomina una event definition diversa da quella del trigger. L'export contiene due
event definition `EmailAudience`: quella del trigger, su `DE_OE_Entry`, e un'altra, su `DE_OE_Archive`, che
nessun trigger usa (anche il pilota ha due eventi).

## Journey

```
SPLIT-1 "Opt-in"             Event.<chiave del trigger>.Optin Is true      -> SPLIT-2
                             remainder                                     -> UPDATE-3 "Not opted in"
SPLIT-2 "Archived segment"   Event.<chiave dell'altro evento>.Segment Equal 'Gold' -> UPDATE-1 "Gold archive"
                             remainder                                     -> UPDATE-2 "Other archive"
```

Tabelle: `DE_OE_Entry` (ingresso: `SubscriberKey`, `EmailAddress`, `Optin`), `DE_OE_Archive` (`SubscriberKey`,
`EmailAddress`, `Segment`), `DE_OE_Log` (solo scritta).

## Risposta attesa, passo per passo

1. **SPLIT-2 non supportato.** Spec, "Data sources of a condition": "A key naming an event definition other than
   the trigger's is unsupported." Entrambi gli outcome di SPLIT-2 sono **non coperti**, come elemento non
   supportato. La condizione non va letta su `DE_OE_Entry` né su `DE_OE_Archive`.
2. **SPLIT-1 supportato**: chiave del trigger, colonna `Optin` di `DE_OE_Entry`. `True` -> SPLIT-2; `False`
   (preferito a null) -> UPDATE-3. Entrambi **coperti**.
3. **Casi: 1 scenario, 2 casi, 6 contatti.** Il caso `Optin` `True` si ferma a SPLIT-2.

## Non verificato

- Se `DE_OE_Archive` riceve un CSV: la tabella è nominata solo attraverso una condizione non supportata e la spec
  non lo dice; `csv_tables` non è controllato.
- Il testo del motivo oltre a "non supportat".
