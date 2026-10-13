# once_and_done_entry

Un journey con `entryMode` = `OnceAndDone` (forma presa da un export reale) e l'ingresso da automation, come nel
pilota. Stesso journey, con `SingleEntryAcrossAllVersions`, in `single_entry_all_versions`.

## Journey

```
SPLIT-1 "Permission"   DE_Master.Perm Is true -> UPDATE-1 "Allowed"
                       remainder              -> UPDATE-2 "Not allowed"
```

Tabelle come in `one_split`: `DE_Entry`, `DE_Master` (`Perm` Boolean che ammette null), `DE_Log` (solo scritta);
entry query `SELECT M.ContactId, M.Emailaddress FROM [DE_Master] M`.

## Risposta attesa, passo per passo

1. **Copertura** invariata rispetto al pilota: `Perm` `True` -> UPDATE-1, `False` (preferito a null) -> UPDATE-2.
   **1 scenario, 2 casi, 6 contatti**, entrambi i branch **coperti**.
2. **Modalità di ingresso.** Spec, "Entry source and procedure": "Entry modes `OnceAndDone` (no re-entry) and
   `SingleEntryAcrossAllVersions`: the testbook says every attempt needs a new run identifier." Il testbook contiene
   "run identifier". Con l'ingresso da automation la procedura resta quella del pilota ("Automation (the pilot) | As
   before"), e prima delle estensioni il testbook di un journey da automation non nominava il run identifier: la
   verifica distingue il generatore esteso da quello di prima.

## Non verificato

- La formulazione della nota nel testbook oltre al termine "run identifier".
