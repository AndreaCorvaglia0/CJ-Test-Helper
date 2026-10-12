# journey_data_split

Tre decision split che leggono i Journey Data: le condizioni hanno la chiave
`Event.<eventDefinitionKey>.<campo>` con `IsEphemeralAttribute="true"`, come negli export reali, e leggono le
colonne della data extension di ingresso. Il journey entra da una data extension (`EmailAudience`, Run Once) e non
ha nessun modello di Contact Builder: nessun attribute set, nessuna relazione. Gli operatori sono `IsNull` sulla
chiave del contatto, `Is` su un Boolean, `Equal` su un Text e `GreaterThan` su un Decimal.

## Journey

```
SPLIT-1 "Key missing?"        Event.SubscriberKey IsNull         -> uscita
                              remainder                          -> SPLIT-2
SPLIT-2 "Consent"             Event.HasConsent Is true           -> SPLIT-3
                              remainder                          -> UPDATE-3 "No consent"
SPLIT-3 "Segment and score"   Event.Segment Equal 'Premium'      -> UPDATE-1 "Premium offer"
                              Event.Score GreaterThan 50         -> UPDATE-2 "Score offer"
                              remainder                          -> UPDATE-4 "Standard offer"
```

Tabelle: `DE_JD_Entry` (ingresso, sendable su `SubscriberKey`, chiave primaria non null; `EmailAddress`;
`Segment` Text(20), `Score` Decimal(18,2), `HasConsent` Boolean, tutti ammettono null). `DE_JD_Log` è scritta
dai quattro Update contact e non è letta da nessuno.

## Risposta attesa, passo per passo

1. **Le condizioni leggono la tabella di ingresso.** Spec, "Data sources of a condition": "A condition key
   `Event.<eventDefinitionKey>.<Field>` (marked `IsEphemeralAttribute="true"`) reads column `Field` of the data
   extension of the trigger's entry event." L'evento del trigger è legato a `DE_JD_Entry`, quindi i campi letti
   sono `DE_JD_Entry.SubscriberKey`, `.HasConsent`, `.Segment`, `.Score`. Nessuna condizione è non supportata:
   `unsupported` vuoto.
2. **Tabelle con un CSV: solo `DE_JD_Entry`.** "Entry table ... Yes"; `DE_JD_Log` è "Written-only table ... No".
   Livello: la tabella di ingresso è la radice a una riga per contatto, quindi `contact`.
3. **SPLIT-1: `path_a` non raggiungibile.** `SubscriberKey` è la chiave del contatto (campo sendable della
   tabella di ingresso). Spec, "Data generation rules", priorità 1: "Key or join field | Generated key", e la
   chiave non ammette null nello schema. `IsNull` non è mai vero: `path_a` è **non coperto, non raggiungibile**,
   il remainder è **coperto**. La regola "row present / row absent" non c'entra: vale solo per "A contact-level
   table other than the entry table".
4. **Valori.** Spec, passo 4: valori citati, un valore "other", null quando lo schema lo ammette. Per i confronti
   numerici vale l'estensione: "Coverage values are chosen strictly inside the ranges the conditions define, never
   on a bound." `GreaterThan 50` definisce gli intervalli (-inf, 50) e (50, +inf): un valore interno a ciascuno,
   mai 50.
5. **SPLIT-2 e SPLIT-3: tutti i branch coperti.** `HasConsent` `True` porta a SPLIT-3, `False` al remainder.
   A SPLIT-3 gli outcome sono valutati in ordine: `Premium` -> `path_a`; non `Premium` e `Score` > 50 -> `path_b`;
   non `Premium` e `Score` < 50 -> remainder.
6. **Casi.** Ogni percorso finisce dopo uno solo degli outcome terminali raggiungibili (SPLIT-2 remainder,
   SPLIT-3 `path_a`, `path_b`, remainder): almeno 4 casi, e 4 bastano. Nessun campo a livello di scenario:
   **1 scenario, 4 casi, 12 contatti**.
7. **Valori preferiti.** Spec: "Among values that cover the same branches, the generator prefers those whose path
   rests on no unverified assumption: not null, row present." Quindi:
   - il caso di SPLIT-2 remainder ha `HasConsent` = `False`, non null (null porterebbe allo stesso branch solo
     grazie all'assunzione che null non soddisfa `Is true`);
   - nei casi di `path_b` e del remainder di SPLIT-3, `Segment` è un valore non null diverso da `Premium`;
   - `Score` è > 50 nel caso di `path_b` e < 50, non null, nel caso del remainder (né 50 né vuoto).

## Non verificato

- Il valore esatto di `Segment` ("other") e di `Score`: la spec fissa solo l'intervallo.
- Il caso di `path_a` di SPLIT-3 lascia `Score` libero.
- La procedura Run Once nel report e nel testbook: la verifica `run_once_entry`.
