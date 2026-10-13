# row_absent_isnull

Il test di esistenza di una riga: uno split chiede "il contatto ha una riga in `DE_RA_Form`?" con `IsNull` sulla
chiave della tabella, come il journey reale che controlla se il contatto ha compilato un form. `DE_RA_Form` è un
attribute set collegato al contatto da una relazione group-to-set su `SubscriberKey`; la data extension di
ingresso non è in Contact Builder ed entra da Run Once.

## Journey

```
SPLIT-1 "Form submitted?"   DE_RA_Form.SubscriberKey IsNull  -> UPDATE-1 "No form"
                            remainder                        -> SPLIT-2
SPLIT-2 "Consent"           DE_RA_Form.Consent Is true       -> UPDATE-2 "Consent given"
                            remainder                        -> UPDATE-3 "No consent"
```

Tabelle: `DE_RA_Entry` (ingresso: `SubscriberKey`, `EmailAddress`), `DE_RA_Form` (`SubscriberKey` chiave
primaria, `Consent` Boolean e `SubmittedOn` Date che ammettono null), `DE_RA_Log` (solo scritta).

## Risposta attesa, passo per passo

1. **Livello.** `DE_RA_Form` è collegata al contatto sul campo che contiene la chiave del contatto: a livello di
   contatto (spec, passo 3, e "Table levels keep the rule of 'Classify fields by level' (join field)").
2. **Variabile riga presente / assente.** Spec, "Row present or absent": "A contact-level table other than the entry
   table, whose existence a split tests (`IsNull` or `IsNotNull` on its field linked to the contact key ...), gets
   a contact-level variable 'row present / row absent'." SPLIT-1 fa proprio questo. Non c'è una entry query, quindi
   nessun join la esclude.
3. **Semantica.** "On an absent row, `IsNull` on any of its fields is true and every other operator is false
   (confirmed: a contact with no row reads its key as null)." Con la riga presente, `SubscriberKey` contiene la
   chiave generata (priorità 1 delle regole dei dati), quindi `IsNull` è falso.
4. **Simulazione.**
   - riga assente -> SPLIT-1 `path_a` -> UPDATE-1;
   - riga presente, `Consent` `True` -> SPLIT-1 remainder -> SPLIT-2 `path_a` -> UPDATE-2;
   - riga presente, `Consent` `False` o null -> SPLIT-2 remainder -> UPDATE-3.
   Tutti e quattro i branch sono **coperti**.
5. **Casi: 1 scenario, 3 casi, 9 contatti.** Per UPDATE-3 vale la preferenza "not null, row present": riga presente
   e `Consent` = `False`.
6. **CSV.** "A contact whose row is absent has no row in that table's CSV. This is the only exception to 'each
   contact row finds its rows in the linked tables'." I 3 contatti del caso UPDATE-1 non hanno righe in
   `DE_RA_Form`; i 6 degli altri due casi ne hanno una ciascuno. I trust check devono passare con questa eccezione.
7. **Nessuna cella con uno spazio.** "A null value is an empty CSV cell ... A cell holding a space would be a value,
   so the generator never writes one." (`csv_no_space_cells`).

## Non verificato

- Come la variabile riga presente / assente compare in `contact_values` e nel testbook: l'esempio guarda le righe
  dei CSV (`has_row`).
- Il valore di `SubmittedOn` nelle righe presenti.
