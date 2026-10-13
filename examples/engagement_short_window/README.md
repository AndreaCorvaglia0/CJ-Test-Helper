# engagement_short_window

Due open split, ciascuno dopo la sua email e un wait by duration fisso: 5 minuti prima del primo (come nel journey
reale da cui è presa la forma), 2 giorni prima del secondo. Il tester deve aprire l'email prima che il contatto
arrivi allo split: con 5 minuti la finestra è sotto l'ora e serve un warning, con 2 giorni no.

## Journey

```
SPLIT-1 "Permission"   DE_Master.Perm Is true -> EMAIL-1 "Flash Offer" -> WAIT-1 (5 minuti) -> ENGAGE-1
                       remainder              -> EMAIL-2 "Slow Digest" -> WAIT-2 (2 giorni) -> ENGAGE-2
ENGAGE-1 "Open Flash Offer"  (open su EMAIL-1)   Yes -> uscita   No -> uscita
ENGAGE-2 "Open Slow Digest"  (open su EMAIL-2)   Yes -> uscita   No -> uscita
```

Tabelle come in `engagement_after_join`: `DE_Entry`, `DE_Master` (`Perm` Boolean che ammette null), `DE_Log`;
ingresso da automation. Entrambe le email hanno un link. Impostazioni: inbox reale `cj.tester@example.com`.

## Risposta attesa, passo per passo

1. **Branch.** Ogni engagement split è raggiunto solo dopo la sua email, quindi lo Yes è raggiungibile ("The Yes
   branch counts as reachable only if the path sent the referenced email earlier"). Gli Yes sono **coperti con
   azione manuale** (open, inbox reale); i No sono **coperti** da contatti che non fanno nulla. SPLIT-1: entrambi
   **coperti** (dai casi senza azione manuale).
2. **Casi.** Quattro outcome terminali (ENGAGE-1 Yes, ENGAGE-1 No, ENGAGE-2 Yes, ENGAGE-2 No): **1 scenario,
   4 casi, 12 contatti**. `Perm` = `True` per i casi di ENGAGE-1, `False` (preferito a null) per quelli di
   ENGAGE-2. Ogni caso termina sull'engagement split da cui esce.
3. **Finestra.** Spec, "Honest outcomes": "The deadline of a manual open or click is computed from the waits between
   the email and the engagement split, with a warning when the window is under one hour." Tra EMAIL-1 ed ENGAGE-1 c'è
   solo WAIT-1, 5 minuti: c'è un warning che riguarda questa email, questo split o questo wait. Tra EMAIL-2 ed
   ENGAGE-2 ci sono 2 giorni: nessun warning nomina `Slow Digest`, `ENGAGE-2` o `WAIT-2`.
4. **Durata minima.** "The testbook gives each case's minimum duration.": il testbook contiene una durata minima.

## Non verificato

- La scadenza esatta di ciascuna open nel testbook (data e ora calcolate dall'ora di generazione).
- Dove sta il warning: l'esempio guarda i warning del generatore (lettura, tabelle, coverage, dati), non il testo
  del report, che nomina comunque email, split e wait nelle sezioni sui casi.
