# assumptions_wait

Il complemento di `assumptions_minimal`: un journey con un wait by attribute su un campo Date. Attiva tre delle sei
assunzioni della spec e non le altre tre. Spec, "Honest outcomes": "report.md lists only the assumptions the export
triggers."

## Journey

```
WAIT-1 "on WaitOn"   wait by attribute su DE_Master.WaitOn (Date)  -> SPLIT-1
SPLIT-1 "Score"      DE_Master.Score GreaterThan 50 -> UPDATE-1 "High score"
                     remainder                      -> UPDATE-2 "Low score"
```

Tabelle (ingresso da automation, come nel pilota): `DE_Entry`, `DE_Master` (`ContactId`, `FirstName`, email, telefono,
`WaitOn` Date, `Score` Number), `DE_Log` (solo scritta).

## Risposta attesa, passo per passo

1. **Copertura.** Il wait non ramifica (spec: "Wait by attribute: No branching. The date field is filled according to
   the date settings"). `Score`: > 50 per UPDATE-1, non nullo e < 50 per UPDATE-2. **1 scenario, 2 casi, 6 contatti**,
   entrambi i branch **coperti**; due CSV, `DE_Entry` e `DE_Master`, entrambi a livello di contatto.
2. **Assunzioni attivate** (elenco della spec):
   - "A wait-by-attribute whose date is already past ends immediately": c'è un wait by attribute e la data scritta
     (ora di generazione) è già passata quando entra. **Presente.**
   - "The import accepts the chosen date format and `True`/`False` for Booleans": `DE_Master.csv` ha una colonna Date
     (`WaitOn`). **Presente.**
   - "The time zone applied to a wait date": è la data di un wait. **Presente.**
3. **Assunzioni non attivate:**
   - primo match: lo split ha una sola condizione (vedi `assumptions_minimal`);
   - confronto di testo: nessuna condizione su un testo;
   - engagement split: non ce n'è.
   Il report non le elenca.

## Non verificato

- La formulazione esatta delle assunzioni (si accettano più varianti italiane).
- Le assunzioni dell'ingresso da automation, che la spec non elenca tra le sei.
