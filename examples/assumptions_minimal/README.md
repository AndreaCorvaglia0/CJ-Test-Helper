# assumptions_minimal

Un journey che non attiva nessuna delle sei assunzioni della spec ("Assumptions to verify and known limits"):
report.md non deve elencarne nessuna. Spec, "Honest outcomes": "report.md lists only the assumptions the export
triggers."

## Journey

```
SPLIT-1 "Score"   Event.Score GreaterThan 50  -> UPDATE-1 "High score"
                  remainder                   -> UPDATE-2 "Low score"
```

Tabelle: `DE_AM_Entry` (ingresso Run Once: `SubscriberKey` Text, `EmailAddress`, `Score` Number, ammette null),
`DE_AM_Log` (solo scritta, nessun CSV).

## Risposta attesa, passo per passo

1. **Copertura.** `Score` è Journey Data, a livello di contatto. Intervalli (50, +inf) e (-inf, 50]; valori
   strettamente dentro e non nulli: > 50 per UPDATE-1, < 50 per UPDATE-2 (mai 50). **1 scenario, 2 casi, 6 contatti**,
   entrambi i branch **coperti**.
2. **Le sei assunzioni, una per una** (elenco della spec) e perché nessuna è attivata:
   - "Decision split outcomes are evaluated in order and the first match wins": lo split ha una sola condizione e il
     remainder; con una sola condizione l'ordine non può cambiare il risultato.
   - "Text comparisons: whether `Email` and `EMAIL` are treated as equal": nessuna condizione confronta un testo.
   - "A wait-by-attribute whose date is already past ends immediately": nessun wait.
   - "The import accepts the chosen date format and `True`/`False` for Booleans": il solo CSV (`DE_AM_Entry`) ha colonne
     Text, EmailAddress e Number; nessuna Date e nessun Boolean.
   - "An engagement split is evaluated when the contact reaches it": nessun engagement split.
   - "The time zone applied to a wait date": nessun wait.
   Il report quindi non contiene nessuna di queste sei assunzioni. Il controllo cerca le frasi con cui il report le
   enuncia (italiano, libere nella forma: si accettano più varianti) e non fa un confronto sul numero di righe, che la
   spec non fissa.
3. L'ingresso Run Once ha le sue assunzioni (lo scheduler di Journey Builder), che la spec non elenca tra le sei:
   non sono controllate né in positivo né in negativo.

## Non verificato

- Che il report elenchi comunque l'assunzione sul primo match con una sola condizione: la lettura "serve almeno due
  condizioni" è una lettura della frase della spec ("the first match wins"), non una citazione. Se l'esempio fallisse
  solo su questa riga, la spec va interpretata, non il codice corretto.
- Il testo esatto delle assunzioni che il report elenca.
