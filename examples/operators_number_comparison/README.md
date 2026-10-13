# operators_number_comparison

Gli operatori numerici `LessThan`, `GreaterThanOrEqual` e `LessThanOrEqual` sullo stesso campo Number, in tre split in
serie. Spec, "Operators, types and values": questi tre operatori sono nell'elenco dei supportati e "Coverage values
are chosen strictly inside the ranges the conditions define, never on a bound". Il campo è Contact Data su una tabella a
livello di contatto con ingresso da automation, come `between_inclusive`, per isolare gli operatori.

## Journey

```
SPLIT-1 "Below 50"      Score LessThan 50            -> UPDATE-1 "Low score"
                        remainder                    -> SPLIT-2
SPLIT-2 "100 or more"   Score GreaterThanOrEqual 100 -> UPDATE-2 "High score"
                        remainder                    -> SPLIT-3
SPLIT-3 "Up to 75"      Score LessThanOrEqual 75     -> UPDATE-3 "Mid low score"
                        remainder                    -> UPDATE-4 "Mid high score"
```

`DE_Master.Score` è Number e ammette null.

## Risposta attesa, passo per passo

1. **Intervalli** (outcome in ordine, vince il primo vero):
   - SPLIT-1 `path_a`: Score < 50. Estremo 50 escluso dall'operatore; dentro: ogni valore < 50.
   - SPLIT-1 remainder, raggiunto da SPLIT-2: Score >= 50 (o null).
   - SPLIT-2 `path_a`: Score >= 100. L'estremo 100 è incluso dall'operatore, ma la spec dice "never on a bound":
     dentro significa > 100.
   - SPLIT-2 remainder, raggiunto da SPLIT-3: 50 <= Score < 100 (o null).
   - SPLIT-3 `path_a`: Score <= 75, quindi [50, 75]; dentro: 50 < Score < 75 (50 e 75 sono estremi).
   - SPLIT-3 remainder: 75 < Score < 100 (o null).
2. **Valori.** Spec: "the generator prefers those whose path rests on no unverified assumption: not null". Il valore
   null non è mai necessario: ogni outcome ha un numero. Quindi:
   - UPDATE-1: non nullo, < 50;
   - UPDATE-2: > 100;
   - UPDATE-3: tra 50 e 75, estremi esclusi;
   - UPDATE-4: non nullo, tra 75 e 100, estremi esclusi.
3. **Branch.** Tutti e 6 **coperti**: nessun outcome è reso irraggiungibile da quelli prima.
4. **Conteggi.** Quattro outcome terminali raggiungibili (UPDATE-1..4), un solo campo a livello di contatto:
   **1 scenario, 4 casi, 12 contatti**. Un caso per outcome terminale è anche il minimo: ogni percorso finisce in un
   Update diverso e un contatto segue un solo percorso.

## Non verificato

- I valori esatti (la spec fissa solo l'intervallo, verificato con `contact_constraints`).
- Come Salesforce valuta questi operatori su null: non serve, perché il generatore preferisce valori non nulli.
