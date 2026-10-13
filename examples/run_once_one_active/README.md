# run_once_one_active

"Un solo scenario attivo" con un ingresso Run Once. Spec, "Entry source and procedure", riga "Data extension, Run
Once": "All scenarios enter together, so 'one active scenario at a time' is not offered."

## Journey

```
SPLIT-1 "Channel"   DE_RS_Config.CHANNEL Equal 'Email'  -> UPDATE-1 "Email campaign"
                    remainder                           -> UPDATE-2 "Other campaign"
```

Tabelle: `DE_RS_Entry` (ingresso Run Once: `SubscriberKey`, `EmailAddress`, `CampaignName`), `DE_RS_Config`
(`CampaignName` chiave, `CHANNEL`, `ACTIVE` Boolean), `DE_RS_Log` (solo scritta). Catena di Contact Builder: gruppo
-> `DE_RS_Entry` (`SubscriberKey`) -> `DE_RS_Config` (`CampaignName`), come Entry -> Config nel pilota.

## Impostazioni

`one_active_scenario` = true e `activation_field` = `DE_RS_Config.ACTIVE`. Senza entry query nessun campo di
attivazione verrebbe suggerito ("suggested from the entry query filters"), quindi senza queste impostazioni l'esempio
non proverebbe nulla. Forzarle simula un tester che chiede lo scenario attivo uno alla volta su un ingresso Run Once.

## Risposta attesa, passo per passo

1. **Livelli.** Spec, "Classify fields by level": una tabella è a livello di scenario quando è unita su un campo che
   non è la chiave del contatto. `DE_RS_Config` è unita su `CampaignName`: **scenario**. `DE_RS_Entry` è la tabella di
   ingresso con una riga per contatto: **contatto**. Due CSV.
2. **Scenari.** `CHANNEL` è a livello di scenario: i due outcome di SPLIT-1 leggono valori diversi della stessa riga e
   uno scenario non può attraversarli insieme (spec, "Group into scenarios and cases": "Paths sharing the same
   scenario-level values form one scenario"). `Email` -> UPDATE-1, ogni altro valore -> UPDATE-2.
   **2 scenari, 2 casi (uno per scenario), 6 contatti**; entrambi i branch **coperti**.
3. **Procedura.** "All scenarios enter together": con Run Once entrano tutti gli scenari insieme, quindi il report dice
   che gli scenari **entrano insieme** e non dà la procedura "una riga attiva alla volta" (non dice di impostare
   ACTIVE su una riga e False sulle altre, né di passare allo scenario successivo). Se l'impostazione forzata viene
   ignorata, oppure rifiutata con una frase che chiede di rigenerare senza, la spec è rispettata in entrambi i casi: la
   spec dice solo che l'opzione "is not offered".
   Quello che la spec esclude è che la procedura a una riga attiva alla volta venga **offerta**: il controllo cerca le
   sue frasi ("Per rendere attivo", "imposta ACTIVE", "rendi attivo lo scenario successivo") e la riga delle
   impostazioni che dice che è stata applicata ("sì, campo di attivazione"). Se compaiono, l'opzione è stata offerta.

## Non verificato

- Cosa fa il generatore con l'impostazione forzata (ignorarla o chiedere di rigenerare): la spec non lo dice.
- Il valore di `ACTIVE` nel CSV e `active_at_start` di scenarios.csv: `expected.json` non li esprime.
- Il testbook: non ha una chiave per i testi che non deve contenere.
