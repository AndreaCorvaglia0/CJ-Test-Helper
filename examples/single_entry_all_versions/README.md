# single_entry_all_versions

Lo stesso journey di `once_and_done_entry`, con `entryMode` = `SingleEntryAcrossAllVersions` (forma presa da un
export reale). L'ingresso è da automation, come nel pilota.

## Journey

```
SPLIT-1 "Permission"   DE_Master.Perm Is true -> UPDATE-1 "Allowed"
                       remainder              -> UPDATE-2 "Not allowed"
```

## Risposta attesa, passo per passo

1. **Copertura**: come `once_and_done_entry`, **1 scenario, 2 casi, 6 contatti**, entrambi i branch **coperti**
   (`Perm` `True` -> UPDATE-1, `False` preferito a null -> UPDATE-2).
2. **Modalità di ingresso.** Spec: "Entry modes `OnceAndDone` (no re-entry) and `SingleEntryAcrossAllVersions`: the
   testbook says every attempt needs a new run identifier." Il testbook contiene "run identifier".

## Non verificato

- La formulazione della nota nel testbook oltre al termine "run identifier".
