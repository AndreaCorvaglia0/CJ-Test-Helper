# journey_data_snapshot

Lo stesso campo letto in due modi dopo un Update contact che lo riscrive: come Journey Data (la fotografia presa
all'ingresso) e come Contact Data (il valore letto dal vivo). La tabella di ingresso `DE_Snap_Entry` è anche un
attribute set di Contact Builder, collegato al contatto da una relazione group-to-set su `SubscriberKey`.

## Journey

```
SPLIT-1 "Tier at entry"           Event.Tier Equal 'Gold'          -> UPDATE-1 "Downgrade to Silver"
                                  remainder                        -> UPDATE-4 "Not gold"
UPDATE-1                          scrive DE_Snap_Entry.Tier = 'Silver' -> SPLIT-2
SPLIT-2 "Tier from journey data"  Event.Tier Equal 'Gold'          -> SPLIT-3
                                  remainder                        -> uscita
SPLIT-3 "Tier from contact data"  DE_Snap_Entry.Tier Equal 'Silver' (Contact Data) -> UPDATE-2 "Live value seen"
                                  remainder                        -> UPDATE-3 "Live value missed"
```

Tabelle: `DE_Snap_Entry` (ingresso, sendable su `SubscriberKey`; `EmailAddress`; `Tier` Text(20) che ammette
null). `DE_Snap_Log` è scritta da UPDATE-2, -3, -4 e non è letta.

## Risposta attesa, passo per passo

1. **Due sorgenti per lo stesso campo.** Spec, "Data sources of a condition":
   - Journey Data: "Its value is the snapshot taken at entry: later Update contact writes do not change it."
   - Contact Data: "`<AttributeSet>.<Field>` as before, read live when the contact reaches the activity. The rule
     'a later split that reads the same field sees the updated value' applies to Contact Data only."
2. **Valori di `Tier`**: `Gold`, `Silver` (citati), un valore "other", null.
3. **Simulazione.**
   - `Gold`: SPLIT-1 `path_a` -> UPDATE-1 scrive `Silver` nella riga del contatto -> SPLIT-2 legge la fotografia
     d'ingresso, ancora `Gold` -> `path_a` -> SPLIT-3 legge il dato vivo, ora `Silver` -> `path_a` -> UPDATE-2.
   - `Silver`, "other", null: SPLIT-1 remainder -> UPDATE-4.
   Se il generatore applicasse l'Update contact ai Journey Data, il contatto `Gold` finirebbe nel remainder di
   SPLIT-2; se non lo applicasse ai Contact Data, finirebbe in UPDATE-3. L'esempio fallisce in entrambi i casi.
4. **Branch.** SPLIT-2 e SPLIT-3 si raggiungono solo dopo UPDATE-1, dove la fotografia vale sempre `Gold` e il
   dato vivo sempre `Silver`. Quindi SPLIT-2 `path_a` e SPLIT-3 `path_a` sono **coperti**, i due remainder sono
   **non coperti, non raggiungibili**. SPLIT-1: entrambi **coperti**.
5. **Casi.** `Tier` = `Gold` (il valore scritto nel CSV, prima del run) -> UPDATE-2; un altro valore -> UPDATE-4.
   **1 scenario, 2 casi, 6 contatti.** Per il secondo caso vale la preferenza "not null" dell'estensione: `Tier`
   non è vuoto e non è `Gold`.
6. **Tabelle.** `DE_Snap_Entry` è di ingresso, letta dagli split e scritta da UPDATE-1: ha un CSV, livello
   `contact`. `DE_Snap_Log` è solo scritta: nessun CSV.

## Non verificato

- Il valore esatto del secondo caso (`Silver` oppure "other").
- Come il testbook descrive il valore scritto da UPDATE-1.
