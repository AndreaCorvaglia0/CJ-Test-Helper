# CJ Test Helper

Genera dataset di test sintetici per i Customer Journey di Salesforce Marketing Cloud: dati fittizi con chiavi coerenti fra tutte le DE coinvolte, matrice degli esiti attesi e testbook, a partire dall'export Package Manager del journey.

## Installazione (una volta)

Requisiti: Python 3.11 o successivo.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Uso

1. **Esporta il journey** da Package Manager (JSON) selezionando il journey: il pacchetto porta con sé DE, data model di Contact Builder, entry event e automation.
2. **Analizza** il pacchetto:

   ```bash
   .venv\Scripts\python.exe -m cjtest analyze "percorso\export.json"
   ```

   Stampa struttura, variabili e controlli statici, e crea il profilo `profiles/<journey>.json`.
3. **Rivedi il profilo** (vedi sotto) e imposta almeno `settings.engagement_mailbox` se il journey ha engagement split.
4. **Genera** il test run:

   ```bash
   .venv\Scripts\python.exe -m cjtest generate "percorso\export.json"
   ```

   L'output va in `runs/<run id>_<journey>/`.

## Output

| File | Contenuto |
|---|---|
| `import/<DE>.csv` | contatti di test, per le DE a livello contatto: si importano **una volta** per tutto il run |
| `import/<DE scenario>/<Sxx>.csv` | una riga di configurazione per scenario: si importa **prima di ogni esecuzione** |
| `testbook.xlsx` | un test per caso nel formato del testbook (ID, Owner system, Test name, Description, Pre conditions, Detailed steps, Expected result, Status, Note) |
| `expected_matrix.xlsx` | scenari, casi, record, copertura di ogni ramo, controlli statici |
| `report.md` | sintesi, procedura di esecuzione, controlli statici, errori |
| `manifest.json` | esiti attesi in formato macchina (base per il confronto automatico con le evidenze) |
| `profile.json` | copia del profilo usato |

## Procedura di esecuzione

1. Importa i CSV dei contatti nelle rispettive DE (Add and Update).
2. Per ogni scenario, in ordine: importa il CSV di configurazione, poi esegui una volta l'automation di entry. La campagna precedente viene disattivata dalla query di update, quindi non serve attendere la fine del run precedente.
3. Casi engagement: nella casella interna apri/clicca le email indicate **entro la scadenza** riportata nel testbook. I destinatari usano il plus-addressing (`casella+chiavecontatto@dominio`) per distinguere i contatti.
4. Raccogli le evidenze e compila lo Status del testbook.

La scadenza degli engagement è calcolata al momento della generazione (`engagement_wait_hours`, default 24): genera il run a ridosso dell'esecuzione.

## Profilo di test

Dedotto dal pacchetto, da rivedere prima della prima generazione:

| Chiave | Significato |
|---|---|
| `de_levels` | `contact` o `scenario`: le DE a livello scenario hanno un valore per campagna/esecuzione |
| `injection_des` | DE da popolare con i dati di test |
| `field_links` | campi che portano la chiave contatto o la chiave scenario |
| `fixed_values` | valori imposti (dedotti dalla WHERE della query di entry) |
| `date_rules` | `yesterday` / `today` / `tomorrow` per le date (finestre di campagna, attese per attributo) |
| `settings.records_per_case` | record per caso (default 3) |
| `settings.control_group_sample_size` | contatti dello scenario statistico sul random split |
| `settings.fictitious_email_domain` | dominio non consegnabile (default `example.invalid`) |
| `settings.fictitious_phone` | telefono fittizio |
| `settings.engagement_mailbox` | casella reale per i rami engagement "Yes" |
| `settings.case_insensitive_text` | confronto testi nei criteri senza distinzione maiuscole/minuscole |

## Come vengono derivati i casi

Vedi [docs/design.md](docs/design.md). In breve: le variabili degli split vengono divise in livello scenario (uguali per tutti i contatti di un'esecuzione) e livello contatto; il motore sceglie il minor numero di scenari che copre ogni ramo di ogni split, evitando i random split, e dentro ogni scenario genera un caso per ogni percorso distinto. I random split vengono verificati con uno scenario statistico.

## Da verificare sulla piattaforma (smoke test)

Il tool si basa su queste assunzioni, da confermare con un primo run da pochi record:

1. Gli outcome di un decision split sono valutati nell'ordine, vince il primo che corrisponde.
2. I confronti di testo nei criteri non distinguono maiuscole/minuscole.
3. Un'attesa per attributo con data nel passato termina subito.
4. I formati data (`%Y-%m-%d`) e data-ora (`%Y-%m-%d %H:%M`) sono accettati dall'import.
5. L'engagement split valuta aperture/click nel momento in cui il contatto lo raggiunge.

## Test

```bash
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

Per includere il test sul journey pilota imposta la variabile `CJTEST_PILOT` con il percorso dell'export.
