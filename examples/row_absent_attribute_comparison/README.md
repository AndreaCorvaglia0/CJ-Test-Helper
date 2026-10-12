# row_absent_attribute_comparison

Il test di esistenza scritto come confronto tra attributi, nella forma degli export reali: la chiave di una tabella
collegata al contatto `Equal` la `SubscriberKey` dei Journey Data. Nell'XML il `<Value>` è vuoto e l'altro lato del
confronto è in `ValueParameterName="Event.<eventDefinitionKey>.SubscriberKey"`.

## Journey

```
SPLIT-1 "Opt-in on file?"   DE_AC_Optin.SubscriberKey Equal [Event.SubscriberKey]  -> SPLIT-2
                            remainder                                             -> UPDATE-3 "No opt-in"
SPLIT-2 "Channel"           DE_AC_Optin.Channel Equal 'SMS'                       -> UPDATE-1 "SMS opt-in"
                            remainder                                             -> UPDATE-2 "Other opt-in"
```

Tabelle: `DE_AC_Entry` (ingresso da Run Once, sendable su `SubscriberKey`), `DE_AC_Optin` (`SubscriberKey`
chiave primaria, `Channel` Text(20) che ammette null; attribute set collegato al contatto da una relazione
group-to-set su `SubscriberKey`), `DE_AC_Log` (solo scritta).

## Risposta attesa, passo per passo

1. **Forma supportata.** Spec, "Data sources of a condition": "A condition whose value is another attribute
   (`ValueParameterName`, or `ValueIsReference`) is supported only in the form 'key field of a contact-level linked
   table `Equal` the contact key', read as 'the contact has a row in that table'." Qui:
   `DE_AC_Optin.SubscriberKey` è il campo collegato alla chiave del contatto di una tabella a livello di contatto;
   `Event.<chiave del trigger>.SubscriberKey` è il campo sendable della tabella di ingresso, cioè la chiave del
   contatto. La condizione significa "il contatto ha una riga in `DE_AC_Optin`". Non va letta come confronto con
   un valore vuoto: così `path_a` non sarebbe mai vero.
2. **Variabile riga presente / assente.** "Row present or absent": la tabella è a livello di contatto, non è quella
   di ingresso, e uno split ne controlla l'esistenza "(... or the attribute comparison above)".
3. **Simulazione.**
   - riga presente, `Channel` = `SMS` -> SPLIT-1 `path_a` -> SPLIT-2 `path_a` -> UPDATE-1;
   - riga presente, `Channel` diverso da `SMS` -> SPLIT-2 remainder -> UPDATE-2;
   - riga assente -> la condizione è falsa ("every other operator is false" su una riga assente) -> SPLIT-1
     remainder -> UPDATE-3.
   Tutti e quattro i branch sono **coperti**.
4. **Casi: 1 scenario, 3 casi, 9 contatti.** Nel caso UPDATE-2 `Channel` non è vuoto (preferenza "not null").
5. **CSV.** I 3 contatti del caso UPDATE-3 non hanno righe in `DE_AC_Optin`; gli altri 6 ne hanno una
   ("A contact whose row is absent has no row in that table's CSV").

## Non verificato

- Il valore "other" esatto di `Channel`.
- Il testo con cui report e testbook spiegano la lettura "il contatto ha una riga".
