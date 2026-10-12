# update_inserts_row

Un Update contact scrive in una tabella di cui uno split controlla l'esistenza della riga. Per un contatto senza
riga, l'update la inserisce: un secondo test di esistenza, dopo l'update, deve vederla presente.

## Journey

```
SPLIT-1 "Visit on file?"   DE_UI_Visit.SubscriberKey IsNull -> UPDATE-1 "Record visit" -> SPLIT-2
                           remainder                       -> UPDATE-3 "Returning visitor"
UPDATE-1                   scrive DE_UI_Visit.Source = 'Journey', DE_UI_Visit.VisitedOn = {{DateTime.Now}}
SPLIT-2 "Visit recorded?"  DE_UI_Visit.SubscriberKey IsNull -> UPDATE-2 "Visit still missing"
                           remainder                       -> UPDATE-4 "Visit recorded"
```

Tabelle: `DE_UI_Entry` (ingresso da Run Once), `DE_UI_Visit` (`SubscriberKey` chiave primaria, `Source`,
`VisitedOn`; attribute set collegato al contatto da una relazione group-to-set su `SubscriberKey`), `DE_UI_Log`
(solo scritta).

## Risposta attesa, passo per passo

1. **Variabile riga presente / assente** su `DE_UI_Visit`: tabella a livello di contatto, non di ingresso, con un
   test di esistenza (`IsNull` sul campo collegato alla chiave del contatto).
2. **L'update inserisce la riga.** Spec, "Row present or absent": "An Update contact on that table inserts the row:
   later reads see it present." `DE_UI_Visit` è Contact Data, quindi vale anche "a later split that reads the same
   field sees the updated value".
3. **Simulazione.**
   - riga assente -> SPLIT-1 `path_a` -> UPDATE-1 inserisce la riga del contatto -> SPLIT-2: la chiave non è più
     null -> remainder -> UPDATE-4;
   - riga presente -> SPLIT-1 remainder -> UPDATE-3.
4. **Branch.** SPLIT-1: entrambi **coperti**. SPLIT-2 si raggiunge solo dopo UPDATE-1, quando la riga c'è sempre:
   `path_a` è **non coperto, non raggiungibile**, il remainder è **coperto**. Se l'update non inserisse la riga, il
   contatto finirebbe in UPDATE-2 e l'esempio fallirebbe.
5. **Casi: 1 scenario, 2 casi, 6 contatti.** Il CSV è lo stato prima del run: i 3 contatti del caso UPDATE-4 non
   hanno una riga in `DE_UI_Visit` (la crea il journey), i 3 del caso UPDATE-3 ne hanno una.
6. **Tabella letta e scritta.** `DE_UI_Visit` è letta dagli split: ha un CSV anche se è scritta da UPDATE-1 (la
   regola "Written-only" vale solo per le tabelle "never read by a split").

## Non verificato

- Come il testbook descrive i valori scritti da UPDATE-1 nella riga inserita.
