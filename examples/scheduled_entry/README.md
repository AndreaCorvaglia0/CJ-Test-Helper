# scheduled_entry

Un journey che entra da una data extension con pianificazione **ricorrente**: event definition `EmailAudience` con
`metaData.scheduleFlowMode` = `recurring` e un oggetto `schedule` giornaliero. La spec non fissa come si scrive la
pianificazione ricorrente in un export e non c'era un export reale con questa forma: il valore `recurring` e
l'oggetto `schedule` (copiato nella forma da quello del pilota) sono inventati. Per questo la risposta attesa non
dipende dalla grafia: qualunque pianificazione di una data extension che non sia Run Once né un'automation è la riga
"Data extension, recurring schedule" della spec. L'`automationId` è un GUID nudo, come negli altri esempi con
data extension di ingresso.

## Journey

```
SPLIT-1 "Tier"   Event.Tier Equal 'Gold'  -> UPDATE-1 "Gold welcome"
                 remainder                 -> UPDATE-2 "Standard welcome"
```

Tabelle: `DE_SC_Entry` (ingresso: `SubscriberKey`, `EmailAddress`, `Tier` Text, ammette null), `DE_SC_Log`
(solo scritta).

## Risposta attesa, passo per passo

1. **Copertura.** `Tier` è un campo Journey Data della tabella di ingresso, a livello di contatto. `Gold` -> UPDATE-1;
   ogni altro valore -> UPDATE-2. Spec, "Operators, types and values": "the generator prefers those whose path rests
   on no unverified assumption: not null", quindi il caso del remainder ha un valore non vuoto e diverso da `Gold`
   (il valore preciso è libero). Due outcome terminali raggiungibili, un solo campo a livello di contatto:
   **1 scenario, 2 casi, 6 contatti**, entrambi i branch **coperti**, un solo CSV (`DE_SC_Entry`).
2. **Procedura.** Spec, "Entry source and procedure", riga "Data extension, recurring schedule": "Reported as a
   procedure to verify: contacts enter at the next evaluation". La tabella dice che la procedura sta in "report.md
   and the testbook". Quindi report.md e testbook dicono che la procedura è **da verificare**, e il report dice che i
   contatti entrano alla **valutazione successiva** (si controlla la parola "valutazione").
3. **Cosa non deve dire.** Le frasi di Run Once ("only rows present at activation enter; rows imported later never
   do", "a new attempt needs a new journey version") valgono per un'altra riga della tabella: con la pianificazione
   ricorrente non devono comparire ("non entrano mai", "nuova versione").

## Non verificato

- Il resto della formulazione della procedura (come il report dice di importare e di aspettare).
- Se il report segnala che la grafia della pianificazione non è stata verificata: la spec non lo chiede.
