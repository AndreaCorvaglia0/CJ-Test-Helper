# attribute_comparison_unsupported

Un confronto tra due campi ordinari: `DE_AU_Prefs.LastChannel` `Equal` il campo `PreferredChannel` dei Journey
Data, scritto con `ValueParameterName` e `<Value>` vuoto. Non è la forma supportata (chiave della tabella uguale
alla chiave del contatto), quindi va segnalato come non supportato e non letto come confronto con un valore vuoto.

## Journey

```
SPLIT-1 "Active"          DE_AU_Prefs.Active Is true                           -> SPLIT-2
                          remainder                                            -> UPDATE-3 "Inactive"
SPLIT-2 "Same channel?"   DE_AU_Prefs.LastChannel Equal [Event.PreferredChannel] -> UPDATE-1 "Same channel"
                          remainder                                            -> UPDATE-2 "Channel changed"
```

Tabelle: `DE_AU_Entry` (ingresso da Run Once: `SubscriberKey`, `EmailAddress`, `PreferredChannel`),
`DE_AU_Prefs` (`SubscriberKey` chiave primaria, `Active` Boolean, `LastChannel` Text; attribute set collegato al
contatto da una relazione group-to-set su `SubscriberKey`), `DE_AU_Log` (solo scritta).

## Risposta attesa, passo per passo

1. **SPLIT-2 non supportato.** Spec: "Any other form is unsupported and reported; it is never read as a comparison
   with an empty value." `LastChannel` non è il campo chiave della tabella e `PreferredChannel` non è la chiave del
   contatto. Entrambi gli outcome di SPLIT-2 sono **non coperti**, con un motivo che parla di elemento non
   supportato ("Anything else is not an error: it is listed in the report, and the branches behind it are marked
   as not covered"). Letto come `LastChannel = ''`, il generatore troverebbe valori per entrambi i branch:
   l'esempio fallirebbe.
2. **SPLIT-1 supportato**: `Active` `True` -> SPLIT-2; `False` o null -> UPDATE-3. Entrambi **coperti**.
3. **Nessuna variabile riga presente / assente.** Nessuno split controlla l'esistenza di `DE_AU_Prefs` (il confronto
   non supportato non vale come test di esistenza). Spec: "No such variable for tables ... that no split tests for
   existence." Ogni contatto ha la sua riga in `DE_AU_Prefs`.
4. **Casi: 1 scenario, 2 casi, 6 contatti.** `Active` `True` (il percorso si ferma a SPLIT-2) e `Active` `False`
   (UPDATE-3; preferenza "not null").
5. **Apertura del report.** Spec, "Honest outcomes": "report.md and the page open with a warning when unsupported
   elements leave branches not covered." L'apertura del report (il testo prima della seconda sezione `##`) parla di
   un elemento non supportato.

## Non verificato

- Il risultato atteso del caso `Active` `True` nel testbook. La spec chiede: "Past an unsupported element the
  expected result says the path is unknown from that activity on; it never names the unsupported activity as the
  last one reached." Il formato di `expected.json` non vede il testo del testbook caso per caso.
- Dove compare la condizione non supportata (`CoverageResult.unsupported` o un warning): la spec dice solo
  "reported".
