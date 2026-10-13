# operators_text

Gli operatori di testo `BeginsWith`, `EndsWith`, `Contains` e `NotEqual` sullo stesso campo Text, in quattro split in
serie. Spec, "Operators, types and values": sono tutti nell'elenco dei supportati. Il campo è Contact Data su una
tabella a livello di contatto con ingresso da automation, come `between_inclusive`.

## Journey

```
SPLIT-1 "Starts with VIP"  Code BeginsWith 'VIP'     -> UPDATE-1 "VIP code"
                           remainder                  -> SPLIT-2
SPLIT-2 "Ends with -EU"    Code EndsWith '-EU'        -> UPDATE-2 "EU code"
                           remainder                  -> SPLIT-3
SPLIT-3 "Contains TEST"    Code Contains 'TEST'       -> UPDATE-3 "Test code"
                           remainder                  -> SPLIT-4
SPLIT-4 "Not blocked"      Code NotEqual 'BLOCKED'    -> UPDATE-4 "Ordinary code"
                           remainder "Blocked"        -> UPDATE-5 "Blocked code"
```

`DE_Master.Code` è Text(30) e ammette null. Il confronto distingue maiuscole e minuscole (impostazione predefinita
della spec: "The PoC assumes they are different by default").

## Risposta attesa, passo per passo

1. **Raggiungibilità di ogni outcome** (outcome in ordine, vince il primo vero):
   - UPDATE-1: un `Code` che inizia con `VIP` (per esempio `VIP`). Raggiungibile.
   - UPDATE-2: un `Code` che finisce con `-EU` e non inizia con `VIP` (per esempio `-EU`). Raggiungibile.
   - UPDATE-3: un `Code` che contiene `TEST`, non inizia con `VIP` e non finisce con `-EU` (per esempio `TEST`).
     Raggiungibile.
   - UPDATE-4: un `Code` che non è nessuno dei casi sopra e non è `BLOCKED`: qualunque altro valore non vuoto.
     Raggiungibile (il valore "other" della spec: "one extra 'other' value").
   - UPDATE-5, il remainder di SPLIT-4: `NotEqual 'BLOCKED'` falso, cioè `Code` è `BLOCKED` (oppure null, se un
     confronto con null è falso: assunzione non verificata). `BLOCKED` non inizia con `VIP`, non finisce con `-EU` e non
     contiene `TEST` (maiuscole comprese), quindi supera i tre split precedenti. Raggiungibile.
2. **Valori.** Spec: "Field read by a split: the value the case requires, written exactly as in the condition", e "the
   generator prefers those whose path rests on no unverified assumption: not null". Quindi UPDATE-5 ha `Code` =
   `BLOCKED` esatto (non null); UPDATE-4 ha un valore non nullo e diverso da `BLOCKED`. Per i casi di BeginsWith,
   EndsWith e Contains la spec non fissa la stringa: `expected.json` verifica solo l'ultima attività, e il valore
   scritto lo verifica il trust check "ogni contatto simulato dai file segue il percorso previsto".
3. **Branch.** Tutti gli 8 **coperti**.
4. **Conteggi.** Cinque outcome terminali raggiungibili, un solo campo a livello di contatto: **1 scenario, 5 casi,
   15 contatti**.

## Non verificato

- Le stringhe scelte per UPDATE-1, 2 e 3 (la spec non le fissa).
- Come Salesforce valuta `NotEqual` su null.
