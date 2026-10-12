# between_inclusive

`Between` con valore `basso|alto`, estremi inclusi, insieme a `GreaterThan` e `Equal` sullo stesso campo
Number. Verifica tre regole dell'estensione: `Between` è supportato, include entrambi gli estremi, e i valori di
copertura stanno dentro gli intervalli, mai su un estremo. Il campo è Contact Data su una tabella a livello di
contatto, con l'ingresso da automation come nel pilota, per isolare l'operatore dagli altri costrutti nuovi.

## Journey

```
SPLIT-1 "Score band"      (DE_Master.Score, Number, ammette null)
  path_a          Score GreaterThan 20      -> UPDATE-1 "High score"
  path_b          Score Between '10|20'     -> UPDATE-2 "Mid score"
  path_c          Score Equal 20            -> UPDATE-3 "Score twenty"
  remainder_path                            -> UPDATE-4 "Low score"
```

Come negli export reali, la `criteriaDescription` di `path_b` è troncata ("Score between 10"): fa fede il valore
dell'XML, `10|20`.

## Risposta attesa, passo per passo

1. **Operatore e valore.** Spec, "Operators, types and values": "`Between` takes the value `low|high` and includes
   both bounds (confirmed). Field types add Number and Decimal."
2. **Intervalli.** Le condizioni dividono i numeri in (-inf, 10), [10, 20], (20, +inf), più il punto 20 citato da
   `Equal`. Spec: "Coverage values are chosen strictly inside the ranges the conditions define, never on a bound."
   Quindi un valore < 10, un valore strettamente tra 10 e 20, un valore > 20.
3. **SPLIT-1, in ordine** (spec, passo 2: "the first true one wins"):
   - valore > 20 -> `path_a`, **coperto**;
   - 10 < valore < 20 -> `GreaterThan 20` falso, `Between` vero -> `path_b`, **coperto**;
   - 20 -> `GreaterThan 20` falso, `Between 10|20` vero perché gli estremi sono inclusi -> `path_b`. Nessun valore
     arriva a `path_c`: `Equal 20` vale solo per 20, che `path_b` ha già preso. `path_c` è **non coperto, non
     raggiungibile**. Con un `Between` a estremi esclusi, 20 andrebbe a `path_c` e l'esempio fallirebbe;
   - valore < 10 o null -> remainder, **coperto**.
4. **Valori preferiti.** Il remainder si raggiunge con un numero < 10 o con null. Spec: "Among values that cover
   the same branches, the generator prefers those whose path rests on no unverified assumption: not null". Il caso
   del remainder ha un numero < 10, non vuoto. Così sono coperti entrambi i lati di `Between`: sopra (caso di
   `path_a`) e sotto (caso del remainder).
5. **Casi.** Tre outcome terminali raggiungibili, un solo campo a livello di contatto: **1 scenario, 3 casi,
   9 contatti**. Valori: > 20 per UPDATE-1, tra 10 e 20 esclusi per UPDATE-2, < 10 per UPDATE-4; mai 10 né 20.

## Non verificato

- I valori esatti (la spec fissa solo l'intervallo, verificato con `contact_constraints`).
- Il formato del numero nel CSV (`15` o `15.0`): il confronto è numerico.
