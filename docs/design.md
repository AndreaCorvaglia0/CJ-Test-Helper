# CJ Test Helper — Disegno della soluzione (bozza)

> Stato: bozza di lavoro. Il documento finale su template Lutech verrà prodotto a strumento funzionante.

## 1. Obiettivo

Generare dataset sintetici per testare i Customer Journey SFMC prima del go-live: dati fittizi non consegnabili, chiavi coerenti fra tutte le DE coinvolte, matrice degli esiti attesi, export delle evidenze confrontabile con il testbook.

Target: livello 5 dell'indicatore.

| Livello | Contenuto |
|---|---|
| 3 | Struttura del journey da input (export Package Manager), dataset per tutte le DE, chiavi coerenti, matrice esiti attesi, documentazione d'uso |
| 4 | + derivazione struttura via API nell'org Ten, export evidenze confrontabile con il testbook |
| 5 | + routine agentica periodica per gli enhancement, procedura di test formalizzata come standard |

Utenti: consulenti MCC e cliente, una persona per volta, su PC aziendale.

## 2. Architettura

Tool esterno Python (CLI), versionato su GitHub.

```
 input                         modello interno            output
 ─────                         ───────────────            ──────
 export Package Manager ──┐
   (livello 3)            ├──► JourneyModel ──► motore casi ──► generatore dati ──► CSV per DE (import manuale)
 API SFMC Ten ────────────┘    (grafo, DE,      di test          (chiavi coerenti)   matrice esiti attesi (xlsx)
   (livello 4)                  data model,                                          testbook (xlsx)
                                config)                                              controlli statici
                                                  evidenze (data view, Log DE) ──► confronto atteso/osservato
```

- Due adapter di input producono lo stesso `JourneyModel`: il resto del tool non sa da dove arriva la struttura.
- Credenziali Installed Package in Windows Credential Manager, mai nel repo.

## 3. Input livello 3: export Package Manager

Dal JSON (`entities`) il tool legge:

| Entità | Uso |
|---|---|
| `journeys` | attività, outcome, criteri degli split (FilterDefinition XML), attese, entry mode |
| `eventDefinitions` | entry source, DE di entry, schedule |
| `dataExtensions` | schema completo: campi, tipi, lunghezze, PK, nullable, default |
| `attributeGroups` / `attributeSets` / `attributeRelationships` | data model Contact Builder, chiavi di join, cardinalità |
| `automations` / `queryActivities` / `verificationActivities` | come viene popolata la DE di entry e con quali filtri |

I riferimenti `{{mcpm#/entities/...}}` vengono risolti internamente per ottenere nomi di DE e campi.

## 4. Journey pilota: `CJ_SkYDE_NCRM_Demo_final`

- 178 attività: 106 decision split, 6 engagement split, 1 random split (90/10), 11 email, 34 Update Contact, 13 wait (3 by attribute, 10 da 1 minuto), 7 STO wait.
- Entry: `DE_NCM_AdHoc_Entry` via Automation Audience, alimentata dall'automation `A_SkyDE_NCRM_AdHoc_CJ_entry` (ogni 2 ore). Re-entry: sempre (`MultipleEntries`).
- Data model: `DEMO_SkyDE` → `SF_Master_DataExtension_DE` (ContactId) → `DE_NCM_AdHoc_Entry` (ContactId) → `DE_NCRM_AD_HOC_CONFIG` (CampaignName).

Flusso di entry:

1. `Q_Check_Active_campaigns` → `DE_Check_Active_Campaigns`; la verification activity ferma l'automation se c'è più di una campagna attiva.
2. `Q_SKYDE_AdHoc_Target`: Master ⋈ Target (`ContactId = SalesforceId`) ⋈ Config (`Description = CampaignName`), filtrando `ACTIVE = True`, `HAS_RUN = False`, oggi fra `START_DATE` e `END_DATE` → Entry DE, con `ActionId = ContactId_CampaignName_yyyyMMdd_HHmm`.
3. `Q_SKYDE_NCRM_AD_HOC_CONFIGURATION_UPDATE`: imposta `HAS_RUN = True`, `ACTIVE = False`.
4. `Q_SkyDE_AdHoc_Backup`: copia Entry → Backup.

## 5. Logica di derivazione dei casi di test

### 5.1 Variabili

Le condizioni degli split si dividono in due famiglie:

| Livello | Attributi | Conseguenza |
|---|---|---|
| Campagna (Config) | `Control Group Required`, `CHANNEL1..4`, `IGNOREPERM1..4`, `Open_Click_Strategy`, `WAIT1..3` | uguali per tutti i contatti di un'esecuzione; una sola campagna attiva alla volta ⇒ **uno scenario = un'esecuzione sequenziale** |
| Contatto (Master) | `IsMailOffers`, `MarketingPermission`, `PhoneConsent`, `IsDunning` (true/false/null), `EmailOptOut` | combinabili liberamente dentro lo stesso scenario |
| Non deterministiche | random split 90/10, engagement split (open/click) | trattamento dedicato (5.4, 5.5) |

### 5.2 Domini e classi di contatto

Il grafo ha 775.131 percorsi strutturali, ma quasi tutti sono impossibili perché lo stesso attributo viene rivalutato più volte. Invece di enumerare i percorsi, il motore ragiona sui valori:

1. **Dominio di ogni variabile**, dedotto da tipo di campo e criteri: Boolean → `true`, `false` (+ `null` se nullable); testo → ogni valore letterale usato nei criteri + un valore "altro" (+ `null` se nullable); numeri → soglie ±1.
2. **Classi di contatto**: tutte le combinazioni delle variabili contatto vengono raggruppate per il vettore di verità dei criteri che le usano. Due combinazioni nella stessa classe percorrono il journey allo stesso modo. Sul pilota: 243 combinazioni → **8 classi**.
3. **Simulazione**: per uno scenario e una classe, il motore percorre il grafo valutando gli outcome nell'ordine (vince il primo che corrisponde, altrimenti il remainder) e si ramifica solo su engagement e random split.

### 5.3 Scelta degli scenari (copertura decisa)

- **Obiettivo**: ogni outcome di ogni decision ed engagement split coperto almeno una volta.
- Se le combinazioni di scenario sono al massimo 200.000 (pilota: 69.120) vengono **valutate tutte**; gli scenari con lo stesso comportamento collassano (pilota: 6.141 comportamenti distinti).
- **Set cover greedy** con 40 ripartenze randomizzate e rimozione degli scenari ridondanti. Oltre la soglia si passa a un campionamento guidato dagli outcome scoperti.
- Dentro ogni scenario, **tutte le classi di contatto**: ogni percorso distinto diventa un caso. **3 record per caso**.

Esito sul pilota: **40 scenari di percorso** (il limite inferiore calcolato è 33: la soluzione è vicina all'ottimo), **148 casi**, 205 outcome coperti su 257, 5 dallo scenario statistico, **90 irraggiungibili** (vedi 10, anomalia 6).

### 5.4 Random split (control group)

- Gli scenari di percorso escludono i random split, così i percorsi sono deterministici: sul pilota hanno tutti `Control Group Required = false`.
- Uno **scenario statistico** per ogni random split, con N contatti (default 50) e intervallo di accettazione binomiale al 95% (con N=50 e 10%: da 1 a 9 contatti nel ramo del 10%).

### 5.5 Engagement split

- Ramo **Yes** possibile solo se l'email referenziata è stata inviata sul percorso del contatto.
- Ramo **No**: contatti fittizi con email non consegnabile.
- Ramo **Yes**: email reale del tester con plus-addressing (`casella+chiavecontatto@dominio`), per distinguere i contatti di casi diversi nella stessa casella.
- L'engagement split valuta quando il contatto lo raggiunge: negli scenari con casi "Yes" l'attesa per attributo che precede lo split viene impostata **nel futuro** (default +24h) e il testbook riporta la scadenza entro cui aprire/cliccare.

### 5.6 Attese

- Wait by attribute (`WAIT1..3` su Config): nel passato, così l'attesa si chiude subito; nel futuro se precede un engagement "Yes" (5.5).
- Wait by duration: 1 minuto, nessun intervento.
- STO wait (finestra 24h): accettata; il testbook segnala i casi con fino a 24h di latenza.

## 6. Mappa delle DE coinvolte

| DE | Ruolo nel test | Popolata da |
|---|---|---|
| `SF_Master_DataExtension_DE` | anagrafica e consensi del contatto | tool (CSV) |
| `DE_NCRM_AdHoc_Target` | associazione contatto ↔ campagna | tool (CSV) |
| `DE_NCRM_AD_HOC_CONFIG` | parametri di campagna (1 riga per scenario) | tool (CSV) |
| `DE_NCM_AdHoc_Entry` | entry del journey | automation |
| `DE_NCRM_AdHoc_Entry_Backup` | backup entry | automation |
| `DE_Check_Active_Campaigns` | controllo campagna unica | automation |
| `DE_SkyDE_AdHoc_Log_partial` | log azioni DM / OB / CG | journey (Update Contact) → **evidenza** |

Chiavi coerenti:

- `Master.ContactId = Target.SalesforceId`
- `Target.Description = Config.CampaignName`
- `ContactId` univoco per esecuzione (necessario per re-entry e per la PK del Log).

## 7. Regole di generazione dei dati fittizi

| Campo | Regola |
|---|---|
| `ContactId` / `SalesforceId` | `CJT{run}{scenario}{caso}{n}`: prefisso fisso riconoscibile, univoco per esecuzione |
| `CampaignName` | `CJT_{run}_S{nn}` |
| `Emailaddress` | `<chiave>@example.invalid` (non consegnabile per standard RFC 2606); per i casi engagement Yes: casella del tester con plus-addressing |
| `MobilePhone` / `Phone` | `333333333333` |
| Attributi di split | valori derivati dai vincoli del caso |
| Altri campi (AccountId, CustomerNumber, …) | segnaposto sintetici con prefisso `TST`, rispettando tipo e lunghezza; da allineare agli esempi anonimizzati quando disponibili |
| Config | `ACTIVE = True`, `HAS_RUN = False`, `START_DATE = END_DATE = oggi`, `WAIT1..3` nel passato, CHANNEL/IGNOREPERM/flag da scenario |

## 8. Esecuzione

1. Import manuale, **una volta**, dei CSV di Master e Target con i contatti di tutti gli scenari. La query di entry prende solo i Target della campagna attiva, quindi i contatti degli altri scenari restano fermi.
2. Per ogni scenario, in ordine: import della riga di Config (`import/DE_NCRM_AD_HOC_CONFIG/Sxx.csv`) e run once dell'automation `A_SkyDE_NCRM_AdHoc_CJ_entry`. La query di configurazione disattiva la campagna dopo il run, quindi lo scenario successivo può partire subito, senza attendere che i contatti precedenti finiscano il journey.
3. Per i casi engagement Yes: apertura e click delle email ricevute sulla casella interna entro la scadenza.
4. Raccolta evidenze e confronto con la matrice.

Il run va generato a ridosso dell'esecuzione, perché le finestre di campagna e le scadenze engagement sono calcolate alla generazione.

## 9. Evidenze

| Esito atteso | Fonte |
|---|---|
| percorso nel journey | `_JourneyActivity` / `_Journey` |
| email inviata | `_Sent` |
| DM / OB / CG | `DE_SkyDE_AdHoc_Log_partial` |
| SMS | `DE_NCM_AdHoc_Entry.Control Group` (vedi anomalie) |

Output nel formato testbook: `ID | Owner system | Test name | Description | Pre conditions | Detailed steps | Expected result | Status | Note` (Status: TO START, ON GOING, COMPLETED, TO REVIEW).

## 10. Controlli statici (anomalie rilevate sul pilota, da confermare)

1. Gli Update Contact scrivono valori fissi `CampaignName = "DemoSKY"` e `ActionId = "ActionId"` nel Log: essendo parte della PK, i re-entry sovrascrivono le righe precedenti.
2. Le 11 attività "SMS" non scrivono nel Log: impostano `Control Group = 1` sulla DE di entry.
3. 11 split "Phone consent" controllano solo `IsMailOffers`; altri 11 controllano `IsMailOffers + PhoneConsent + IsDunning`.
4. Channel4 confronta con `EMAIL`, gli altri Channel con `Email`.
5. `defaults.mobileNumber` punta all'event definition di `CJ_SkYDE_NCRM_Demo`, non a quella di `_final`.
6. **Tutti e 6 gli engagement split referenziano `EMAILV2-1`** (l'email del canale 1), anche quelli dopo le email dei canali 2 e 3. Sui percorsi che raggiungono gli split `ENGAGEMENTSPLITV2-3/4/5/6` quell'email non viene mai inviata: i rami "Yes" sono irraggiungibili e con loro **88 outcome** sottostanti (90 in totale).
7. Relazione Master → Entry dichiarata 1:1, ma la PK di Entry è `ContactId, ActionId, CampaignName`: più righe per contatto sono possibili.

I controlli sono implementati in modo generico in `cjtest/static_checks.py` e compaiono nel report e nella matrice di ogni run.

## 11. Assunzioni da verificare con uno smoke test

1. Ordine di valutazione degli outcome dei decision split (primo che corrisponde).
2. Confronti di testo case-insensitive.
3. Wait by attribute con data passata: prosegue subito.
4. Formati data e data-ora accettati dall'import.
5. Momento di valutazione dell'engagement split.

## 12. Punti aperti

- Numerosità dello scenario statistico sul control group (proposta 50: con 5 contatti la probabilità di nessun contatto nel control group è ~59%).
- Come garantire che nessuna email parta verso gli indirizzi fittizi: dominio `.invalid` (nessuna consegna, ma SFMC tenta l'invio) oppure Auto-Suppression list (nessun tentativo).
- Esempi anonimizzati dei campi con formato (per ora segnaposto `TST_`).
