# row_absent_other_fields

Il test di esistenza con `IsNotNull` sulla chiave, poi condizioni su un altro campo della stessa tabella, valutate
solo quando la riga manca. Verifica la regola sulle righe assenti per i campi che non sono la chiave: `IsNull` vero,
ogni altro operatore falso.

## Journey

```
SPLIT-1 "Has profile?"   DE_PF_Profile.SubscriberKey IsNotNull -> UPDATE-1 "Profile found"
                         remainder                            -> SPLIT-2
SPLIT-2 "Nickname"       DE_PF_Profile.Nickname IsNull         -> UPDATE-2 "Nickname empty"
                         DE_PF_Profile.Nickname Equal 'Bob'    -> UPDATE-3 "Nickname Bob"
                         remainder                            -> UPDATE-4 "Nickname other"
```

Tabelle: `DE_PF_Entry` (ingresso da Run Once), `DE_PF_Profile` (`SubscriberKey` chiave primaria, `Nickname`
Text(20) che ammette null; attribute set collegato al contatto da una relazione group-to-set su `SubscriberKey`),
`DE_PF_Log` (solo scritta).

## Risposta attesa, passo per passo

1. **Variabile riga presente / assente**: SPLIT-1 controlla l'esistenza con `IsNotNull` sul campo collegato alla
   chiave del contatto ("`IsNull` or `IsNotNull` on its field linked to the contact key").
2. **SPLIT-1.** Riga presente: la chiave è quella generata, non null -> `path_a` -> UPDATE-1. Riga assente:
   "`IsNull` on any of its fields is true and every other operator is false", quindi `IsNotNull` è falso ->
   remainder -> SPLIT-2. Entrambi **coperti**.
3. **SPLIT-2** si raggiunge solo con la riga assente. `Nickname IsNull` è vero su una riga assente -> `path_a` ->
   UPDATE-2, **coperto**. `path_b` (`Equal 'Bob'`) e il remainder non sono mai raggiunti: **non coperti, non
   raggiungibili**. Un contatto con la riga e `Nickname` = `Bob` o vuoto non arriva mai a SPLIT-2, perché esce
   da SPLIT-1 `path_a`.
4. **Casi: 1 scenario, 2 casi, 6 contatti.** Riga presente -> UPDATE-1; riga assente -> UPDATE-2, senza righe in
   `DE_PF_Profile`.

## Non verificato

- Il valore di `Nickname` nelle righe presenti: nessun branch raggiunto lo legge.
