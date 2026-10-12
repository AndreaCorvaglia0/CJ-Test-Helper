# Piano di costruzione e contratto dei moduli

Questo documento è il contratto di lavoro tra i moduli di `cjhelper/`.
`docs/spec.md` è la fonte di verità; questo file fissa solo *come* la spec
è divisa in codice. Se i due documenti non coincidono, vince la spec e questo file è sbagliato.

## Struttura del package

```
cjhelper/
  model.py          shared dataclasses: the only file every module imports (frozen contract)
  loader.py         export JSON -> Package           (resolves {{mcpm#...}}, builds Journey, Tables, Queries)
  criteria.py       FilterDefinition XML -> Formula; operator lookup table and condition evaluation
  sqlparse_lite.py  Query -> ParsedQuery              (sqlglot, T-SQL)
  tables.py         Package -> TableModel             (table selection rule, field levels, key groups)
  graph.py          journey graph walk and simulation (lead)
  coverage.py       value enumeration, set cover, scenarios and cases (lead)
  datagen.py        CoverageResult -> GeneratedData   (data generation rules)
  checks.py         trust checks on the written files (lead)
  outputs.py        CSV, scenarios.csv, report.md, testbook.xlsx, zip
  pipeline.py       generate(source, settings) -> GenerationResult (lead)
  __main__.py       command line: python -m cjhelper export.json --out dir
  app.py            Streamlit page (priority 5, later)
tests/              pytest, one file per module, plus test_examples.py and test_pilot.py
examples/           small hand-made journeys with expected answers (see "Examples")
fixtures/           the pilot export
```

Regole per tutti:

- Python 3.11+, libreria standard più `sqlglot`, `openpyxl`, in seguito `streamlit`. Nient'altro.
- Codice semplice e leggibile. Funzioni brevi, nomi espliciti, nessuna astuzia. I docstring dicono *qual è la regola della spec*.
- `model.py` è congelato. Se serve una modifica, dillo nel report finale; non modificarlo.
- Crea o modifica solo il tuo modulo e il suo file di test. Non toccare mai un altro modulo.
- Non inventare mai il comportamento di Salesforce. Quando la spec non dice nulla, scegli la lettura più semplice, rendila visibile (una voce in `warnings` o una riga del report) ed elencala sotto "Assumptions" nel report finale.
- Nulla è scritto in modo fisso sul journey pilota. I nomi di tabelle e campi vengono dall'export.
- Ogni valore è una `str` in forma CSV, oppure `None` per null. I Boolean sono `"True"`/`"False"`. Le date sono in `Settings.date_format`.
- La ricerca dei campi non distingue maiuscole e minuscole (`Table.field(name)`); viene scritta l'ortografia dello schema.
- Esegui `python -m pytest tests/test_<yourmodule>.py -q` prima di finire.

## Contratti dei moduli

### loader.py

```python
class LoadError(Exception): ...          # invalid JSON, no journey, missing entry table
def load_package(source) -> Package      # source: bytes, str (JSON text or path), dict, or pathlib.Path
```

- Risolvi prima ogni riferimento `{{mcpm#/entities/<kind>/<id>/data/<path>}}`, ovunque (anche le stringhe dentro
  le stringhe, per esempio dentro l'XML dei criteria e dentro l'SQL). Regole: `.../data/name` -> il nome dell'entità;
  `.../data/id` -> l'id dell'entità (la chiave dell'export); `.../data/fields/name:<F>/id` -> il nome del campo `<F>`;
  `.../data/namePrefix` -> il valore se presente, altrimenti `""`; `.../data/eventDefinitionKey` e gli altri
  path esistenti -> il valore; un path mancante -> l'id dell'entità più un warning. I placeholder `{{mcpm:...}}`
  (sender profile, delivery profile) restano come sono. In SQL `prefix[name]` diventa `[name]`.
- Scelta del journey: `selectedEntities.journeys[0]` se presente, altrimenti l'unico journey, altrimenti il primo con un warning.
  Nessun journey -> `LoadError`.
- Activity: mappa `type` tramite `model.ACTIVITY_KINDS`; `WAIT` con `metaData.uiType == "WAITBYATTRIBUTE"`
  è `KIND_WAIT_ATTRIBUTE` (il campo viene da `configurationArguments.waitEndDateAttributeExpression`, l'ultimo
  segmento tra virgolette = campo, il segmento prima = attribute set -> tabella; `metaData.attribute.id` è il ripiego).
  I tipi sconosciuti -> `KIND_UNSUPPORTED` e la chiave va in `Package.unsupported_activities`.
- Decision split: per ogni outcome, `configurationArguments.criteria[outcome.key]` viene letto con
  `criteria.parse_criteria`; l'outcome senza criteria è il remainder (`is_remainder=True`, formula None).
  Il `table` della condizione è il nome dell'attribute set; mappalo al nome della data extension tramite
  `attributeSets[*].storageName` (se nessun set corrisponde, usa il nome stesso, con un warning).
  Tieni gli outcome nell'ordine dell'export (è l'ordine di valutazione).
- Engagement split: `configurationArguments.refActivityCustomerKey` -> `engagement_ref`;
  `statsTypeId` tramite una lookup `ENGAGEMENT_KINDS = {2: "open", 3: "click"}`; ogni altro valore ->
  `engagement_kind = None` e un warning (il branch sarà segnalato come non coperto).
  Gli outcome portano `when` da `arguments.when`.
- Random split: `percentage` da `outcomes[*].arguments.percentage`.
- Email: `configurationArguments.triggeredSend.emailId` si risolve nell'id dell'asset; `email_name` dal nome
  dell'asset, altrimenti dal nome dell'activity. `EmailAsset.has_link` = un `href=` o un `<a ` compare in `views.html.content`
  o in `views.text.content`.
- Update contact: `arguments.activityData.updateContactFields[*]` -> `Write(table, field, value)`; il valore resta
  com'è scritto (`str(value)` per i numeri), `{{DateTime.Now}}` resta letterale.
- Start activity: quella a cui non punta nessun outcome (se ne attende una; se sono più d'una, la prima nell'ordine dell'export più un warning).
- Entry: il `metaData.eventDefinitionId` del trigger -> eventDefinition -> `dataExtensionId` -> tabella;
  `arguments.automationId` -> nome dell'automation. `Journey.default_email_event_key` = la chiave dell'evento dentro
  `defaults.email[0]` (per l'anomalia "il default legge un entry event diverso").
- Tabelle: tutte le `dataExtensions` (e `sharedDataExtensions`), con i campi in ordine `ordinal`.
- Relazioni: `attributeRelationships` -> una `Relationship` per ogni voce di `relationshipAttributes`, con le tabelle
  risolte tramite gli attribute set (`leftItem.identifier` / `rightItem.name`) nei nomi delle data extension.
  `isGroupToSetRelationship` -> `left_table=None`.
- Query: ogni voce di `queryActivities`; `Package.automation_queries[automation name]` elenca i nomi delle query
  in ordine di step (`steps[*].activities[*]` con `objectTypeId == 300`).

Regole aggiunte dalla sezione della spec "Extensions beyond the pilot" (12 ottobre 2026):

- Journey Data: una condizione con chiave `Event.<eventDefinitionKey>.<campo>` (segnata `IsEphemeralAttribute="true"`)
  legge la colonna `<campo>` della tabella di ingresso dell'entry event del trigger: `Condition.table` diventa quella
  tabella e `Condition.source` è `SOURCE_JOURNEY`, così il passo successivo può applicare la regola della fotografia
  all'ingresso. Una chiave che nomina un altro event definition (il pilota ne ha due: vale quello del trigger) rende il
  branch non supportato, con il motivo. Lo stesso per un wait by attribute scritto `{{Event.<key>."Campo"}}`.
- Confronto tra due attributi (`ValueParameterName`, oppure `ValueIsReference`): supportato solo nella forma "campo
  collegato alla chiave del contatto di una tabella a livello di contatto `Equal` la chiave del contatto" (la chiave del
  contatto è il Journey Data dell'entry event del trigger sul campo che contiene la chiave del contatto). La condizione
  viene normalizzata in modo che `table.field` sia il campo collegato e `value_attribute` la chiave del contatto, e si legge
  "il contatto ha una riga in quella tabella". Ogni altra forma rende il branch non supportato, con il motivo; non viene
  mai letta come confronto con un valore vuoto. Un campo è collegato alla chiave del contatto quando lo è per una relazione
  group-to-set, o tramite relazioni tra tabelle a partire da uno di questi campi o dalla chiave del contatto della
  tabella di ingresso.
- `Between` con un valore che non è nella forma `basso|alto` rende il branch non supportato.
- Relazione mancante: una condizione Contact Data su un attribute set che nessuna relazione dell'export nomina rende il
  branch non supportato con il motivo "relazione mancante nell'export"; la tabella va in `Package.missing_relationships`.
- `issues` di Package Manager di livello warning o error (anche nella `cause`), sia in cima all'export sia su ogni
  entità: diventano warning in italiano, tranne quelli su asset e landing page che il journey non usa.
- I warning sugli asset e sulle landing page che nessuna attività Email del journey invia vengono scartati, sia quelli
  della risoluzione dei riferimenti sia le `issues` (anche quando l'asset mancante è un'immagine di un'email inviata).
- Entry source: `EntryEvent.kind` viene dal `type` dell'event definition (`ENTRY_SOURCE_TYPES`) e, per una data
  extension, da `metaData.scheduleFlowMode` (`SCHEDULE_FLOW_MODES`): `ENTRY_AUTOMATION` (il pilota), `ENTRY_RUN_ONCE`,
  `ENTRY_SCHEDULED` (pianificazione ricorrente o non riconosciuta, con un warning), `ENTRY_OTHER` (form CloudPages,
  API event e ogni altro tipo). Restano anche `event_type`, `schedule_mode`, `run_once_mode` ed `entry_filter`.
  `arguments.automationId` diventa `automation_name` solo per un ingresso da automation: su una data extension con la sua
  pianificazione è lo scheduler di Journey Builder (assunzione) e non si segnala nulla.
- Criteri di ingresso (`arguments.criteria` dell'evento, `configurationArguments.criteria` e `filterDefinitionId` del
  trigger, `metaData.criteriaDescription`), goal ed exit criteria non sono modellati: se presenti, un warning.
  `Journey.entry_mode` (`entryMode`), `Journey.goal_count` e `Journey.exit_count` li riportano.
- Un valore predefinito del journey (`defaults.email`, `defaults.mobileNumber`) che legge una colonna che la tabella
  di ingresso non ha -> warning.
- `Field.scale` è letto per i campi Decimal.

### criteria.py

```python
class CriteriaError(Exception): ...
def parse_criteria(xml: str) -> Formula
OPERATORS: dict[str, Callable]            # the one lookup table for operators
def evaluate_condition(cond: Condition, value: Value, field_type: str, case_insensitive: bool) -> bool
class UnsupportedOperator(Exception): ...
```

- XML: `<FilterDefinition><ConditionSet Operator="AND|OR">` che annida `<Condition Key="Set.Field" Operator="..">`
  con il valore in `<Value>` (CDATA, eventualmente vuoto), a volte avvolto in uno o più `<AttributePath>`.
  `Key` si divide al primo `.` in set e campo (i nomi dei campi possono contenere spazi). Un set con un solo elemento
  si riduce a quell'elemento. Un set vuoto o un elemento sconosciuto -> `CriteriaError`.
- Operatori, tutti dalla spec: `Is`, `Equal`, `IsNull` (pilota) più `NotEqual`, `IsNotNull`, `GreaterThan`,
  `LessThan`, `GreaterThanOrEqual`, `LessThanOrEqual`, `Contains`, `BeginsWith`, `EndsWith` (ripresi dal vecchio tool)
  e `Between` (sezione "Extensions beyond the pilot": valore `basso|alto`, estremi inclusi).
- Chiavi: `Event.<eventDefinitionKey>.<campo>` è Journey Data (`source = SOURCE_JOURNEY`, `table` = la chiave
  dell'evento finché il loader non la mappa); `IsEphemeralAttribute="true"` su una chiave in un'altra forma ->
  `CriteriaError`. `ValueParameterName="<attributo>"` (con `<Value>` vuoto) o `ValueIsReference="true"` (l'attributo
  nel `<Value>`) -> `value_attribute`, nessun valore letterale. Funzioni di supporto: `split_attribute(text)` e
  `between_bounds(value)`.
  Semantica in `evaluate_condition` (il valore è sempre la stringa CSV oppure None):
  - Boolean: confronto dopo la conversione in minuscolo, accettando `true/false/1/0`.
  - Text, EmailAddress, Phone, Locale: corrispondenza esatta; non distingue maiuscole e minuscole quando lo dice l'impostazione.
  - Number/Decimal: confronto numerico. Date: leggi entrambi i lati (`YYYY-MM-DD[ HH:MM[:SS]]`, ISO); i valori
    di condizione con la sola data si confrontano sulla parte della data.
  - `IsNull`: None oppure `""`. `IsNotNull`: l'opposto. Ogni altro operatore su None -> False (assunzione, da elencare).
  - `Between`: `basso <= valore <= alto` con il confronto del tipo del campo; un valore non `basso|alto` -> `UnsupportedOperator`.
  - Confronto tra attributi (`value_attribute`, solo `Equal`, forma controllata dal loader): vero quando il campo ha un
    valore, cioè quando il contatto ha la riga.
  - Operatore sconosciuto -> `UnsupportedOperator`.

### sqlparse_lite.py

```python
def parse_query(query: Query, tables: dict[str, Table]) -> ParsedQuery
```

- `sqlglot` con `read="tsql"`. I nomi delle tabelle arrivano come `[Name]` o `ENT.[Name]`; gli alias sono frequenti.
- `sources`: la tabella del FROM e di ogni JOIN. `joins`: le uguaglianze delle clausole ON (concatenate con AND); tutto il resto -> warning.
- `filters`: il WHERE diviso sugli AND di primo livello. `col = 'lit'` -> `EqualityFilter`; `col IS [NOT] NULL` -> `IsNullFilter`;
  un confronto tra la data corrente (`GETDATE()`, `GETUTCDATE()`, `SYSDATETIME()`, con o senza `CAST(... AS DATE)`)
  e una colonna -> `DateBoundFilter` con `bound="start"` quando il filtro significa *now >= column* e `"end"` quando
  significa *now <= column*, da qualunque lato stia la colonna. Tutto il resto, compreso qualsiasi gruppo OR -> `UnsupportedFilter(text)`.
- `select`: colonna -> `SelectColumn`; letterale stringa o numero -> `SelectLiteral`; `FORMAT(GETUTCDATE(), 'fmt')` ->
  `SelectCurrentDate(fmt)`; una chiamata nuda alla data corrente, anche avvolta in `AT TIME ZONE` -> `SelectCurrentDate(None)`;
  `CONCAT(...)` -> `SelectConcat`; tutto il resto -> `SelectUnsupported(text)`. `target_column` = alias, altrimenti il nome della colonna.
  `SELECT *` -> `select_all=True`, select vuota.
- Risoluzione delle colonne: alias -> nome della tabella; non qualificata -> l'unica tabella sorgente che ha quella colonna
  (senza distinguere maiuscole e minuscole, tramite `Table.field`); altrimenti `ColumnRef("", col)` più un warning.
- Non sollevare mai un'eccezione su SQL anomalo: restituisci ciò che è stato compreso e metti il resto in `warnings`.

### tables.py

```python
def build_table_model(package: Package) -> TableModel
```

Chiama `sqlparse_lite.parse_query` da sé. Regole (spec "Table selection" e "Classify fields by level"):

- Tabella di ingresso: `journey.entry_table`. Entry query: la query dell'automation di ingresso il cui target è la tabella
  di ingresso (l'ultima in ordine di step se sono più d'una, con un warning); nessuna -> `entry_query=None` e un warning.
- Tabelle degli split: le tabelle citate in una condizione di un decision split o nel campo di un wait by attribute.
- Tabelle sorgente: FROM/JOIN della entry query, poi per ogni sorgente qualsiasi query il cui target è quella sorgente
  (prima l'automation di ingresso, poi il resto del package), in modo ricorsivo, con un insieme dei già visitati. Registra le query
  lette in `source_queries`.
- Solo scritte: i target degli update contact o delle query che non sono di ingresso, di split o sorgente -> non selezionate.
  Le tabelle senza alcun ruolo -> non selezionate, motivo "not read or written by this journey".
- Chiave del contatto: `(entry table, entry table's sendable_field)`; ripiego sul campo destro della relazione
  group-to-set sulla tabella di ingresso, poi su una chiave primaria di un solo campo; altrimenti un warning e il primo campo della PK.
- Gruppi di chiavi: union-find su ogni uguaglianza di join (join delle query e relazioni); il gruppo che contiene il campo
  della chiave del contatto è `kind="contact"`; un gruppo che contiene un campo di una tabella a livello di scenario è `kind="scenario"`; gli altri `"other"`.
- Livelli: visita in ampiezza dalla tabella di ingresso lungo gli archi di join tra le tabelle selezionate. Una tabella raggiunta tramite
  un campo del gruppo del contatto è a livello di contatto; raggiunta tramite qualsiasi altro campo è a livello di scenario; i vicini
  di una tabella a livello di scenario restano a livello di scenario. I livelli dei campi seguono la loro tabella, tranne i campi di una tabella
  a livello di contatto che appartengono a un gruppo di chiavi dello scenario (contengono la chiave dello scenario).
- `activation_field`: dai filtri della entry query, il primo `EqualityFilter` su un campo Boolean di una tabella
  a livello di scenario con valore `True`/`true`; altrimenti None.
- Ogni decisione finisce in `TableRole.reason` o in `warnings`, in parole semplici.
- Riga presente o assente (sezione "Extensions beyond the pilot"): `TableModel.existence_tested` = tabella -> campo
  collegato alla chiave del contatto, per ogni tabella a livello di contatto, diversa dalla tabella di ingresso, di cui
  uno split valutato verifica l'esistenza (`IsNull` / `IsNotNull` su quel campo, o il confronto tra attributi supportato).
  Mai per le tabelle lette dalle query che popolano la tabella di ingresso (la entry query e quelle che ne alimentano le
  sorgenti). Il motivo della tabella lo dice.
- I livelli restano quelli del campo di join, non la cardinalità dichiarata in Contact Builder.
- Un ingresso non alimentato da un'automation (Run Once, pianificazione ricorrente, form, API event) non ha di norma una
  entry query: non si segnala. Un ingresso da automation la cui automation manca dall'export lo dice così.
- Una tabella in `Package.missing_relationships` resta selezionata (è letta da uno split), a livello di scenario, con
  il motivo "relazione mancante nell'export" al posto dell'assunzione "una riga condivisa da tutti i contatti".
- Le condizioni Journey Data di un altro entry event non nominano alcuna tabella e non producono warning qui.

### Campi del modello aggiunti per le estensioni

| Campo | Significato |
| --- | --- |
| `Condition.source` | `SOURCE_CONTACT` (Contact Data, letto quando il contatto arriva allo split) o `SOURCE_JOURNEY` (Journey Data, fotografia all'ingresso) |
| `Condition.value_attribute` | L'attributo con cui il campo è confrontato, com'è scritto; nella forma supportata la chiave del contatto |
| `Field.scale` | Cifre decimali di un campo Decimal |
| `EntryEvent.kind`, `event_type`, `schedule_mode`, `run_once_mode`, `entry_filter` | Entry source e pianificazione; `ENTRY_*` in `model.py` |
| `Journey.entry_mode`, `goal_count`, `exit_count` | `entryMode` del journey; goal ed exit criteria presenti (non modellati) |
| `Package.missing_relationships` | Tabelle lette da uno split tramite un attribute set senza relazioni nell'export |
| `TableModel.existence_tested` | Tabelle con la variabile "riga presente / riga assente" -> campo collegato alla chiave del contatto |

### graph.py e coverage.py (lead)

Producono `CoverageResult`. Ciò su cui i consumatori possono contare:

- `Scenario.values` ha ogni campo di `CoverageResult.scenario_fields`; `Case.contact_values` ha ogni campo di
  `contact_fields`. I valori sono stringhe CSV oppure None. I valori di testo "other" hanno la forma `OTHER`.
- `Case.steps` è il percorso deterministico completo; per il caso statistico si ferma al random split
  e `Case.random.branches` contiene la continuazione per ogni outcome.
- `Scenario.run_order` parte da 1; gli scenari con azioni manuali vengono per primi. `Case.id` è `S01-C01`.
- `Case.contact_count` è 3 oppure il numero di contatti del caso statistico. `Case.waits` elenca, in ordine, le chiavi delle activity wait attraversate.
- `ManualAction` dice a datagen quali contatti hanno bisogno dell'inbox reale.

### datagen.py

```python
def generate_data(package: Package, model: TableModel, coverage: CoverageResult,
                  settings: Settings, generation_time: datetime) -> GeneratedData
```

Implementa esattamente le "Data generation rules" della spec, in ordine di priorità. Compila anche `Scenario.key` e
`Case.contact_keys` sul posto, e i record `Contact`.

- Righe: una riga di contatto per ogni contatto in ogni tabella selezionata a livello di contatto; una riga per scenario in ogni
  tabella a livello di scenario; le righe della tabella di ingresso sono calcolate dalle espressioni `select` della entry query sulle
  righe sorgente (`SelectColumn` -> valore della riga sorgente collegata; `SelectLiteral`; `SelectCurrentDate` ->
  ora di generazione nel formato .NET convertito in strftime, formato `None` -> `Settings.date_format`;
  `SelectConcat`; `SelectUnsupported` -> placeholder e una voce in `placeholders`). Le colonne di ingresso che non sono nella
  select ricevono il default dello schema (Boolean `False` quando il default lo dice), altrimenti None; una colonna che non ammette null riceve
  un placeholder e una voce in `placeholders`. `select_all` copia le colonne con lo stesso nome.
- Gruppi di chiavi: gruppo del contatto -> `settings.contact_key(n)`, gruppo dello scenario -> `settings.scenario_key(run_order)`,
  altri gruppi -> `TST_<run>_K<n>` condiviso nel gruppo.
- Campi letti dagli split: il valore del caso o dello scenario, esattamente com'è. Null -> None.
- Filtri della entry query: `EqualityFilter` -> quel valore (Boolean scritto `True`/`False`); `DateBoundFilter`
  start -> inizio della finestra, end -> fine della finestra; `IsNullFilter` -> None. Il campo di attivazione sotto
  "one active scenario" è `True` solo per `run_order == 1`.
- Campi dei wait by attribute: ora di generazione + `wait_offset_hours`, oppure + `wait_offset_before_engagement_hours`
  quando un caso di quello scenario attraversa il wait e poi ha un'azione manuale (per scenario per i campi
  a livello di scenario, per contatto per quelli a livello di contatto).
- Campi email (tipo `EmailAddress`, oppure con nome `Email*`): inbox reale con plus-addressing
  `local+<contact key>@domain` per i contatti di un caso con un'azione manuale quando `settings.real_inbox` è impostato,
  altrimenti `<contact key>@example.invalid`. Campi phone: `fake_phone` (hook per il telefono reale: nessuna attività supportata invia
  a un telefono, quindi lascia `uses_real_phone=False` e dillo nel docstring del modulo).
- Altri campi: Text `TST_<field>_<n>` tagliato alla lunghezza (`n` = numero di riga in quella tabella), Boolean default o
  `False`, Date ora di generazione, Number/Decimal `str(n)`, Locale `en-US`.
- `scenarios_rows`: una per scenario: `scenario_key, run_order, has_manual_action, is_statistical, case_count,
  contact_count, first_contact_key, last_contact_key, activate` più una colonna per ogni campo dello scenario `Table.Field`.

### outputs.py

```python
def write_table_csv(data: TableData, table: Table) -> bytes      # UTF-8, comma, header in schema order, \n
def write_scenarios_csv(rows: list[dict]) -> bytes
def write_report(result: GenerationResult) -> str                # markdown, see spec "Outputs"
def write_testbook(result: GenerationResult) -> bytes            # openpyxl, spec columns; priority 4
def build_zip(files: dict[str, bytes]) -> bytes
```

CSV: `csv.writer` con quoting di default, `lineterminator="\n"`, None -> cella vuota. Sezioni del report, in ordine:
riepilogo (scenari, casi, contatti; branch coperti / coperti con azione manuale / non coperti), trust check
(ognuno con superato/non superato e dettagli), tabelle (nome, ruolo, livello, CSV sì/no, motivo), scenari (chiave, valori, casi),
branch non coperti (activity, outcome, motivo), elementi non supportati, warning e pattern sospetti,
assunzioni, impostazioni usate.

### checks.py (lead)

Rilegge i byte dei CSV scritti ed esegue i cinque trust check della spec. Restituisce `list[CheckResult]`.

## Esempi

`examples/<name>/package.json` è un export di package con la stessa forma del pilota (vedi
`docs/export-format.md`), abbastanza piccolo da poterlo ragionare a mano. `examples/<name>/expected.json` è la
risposta ricavata a mano dalla spec. `examples/<name>/README.md` dice cosa verifica l'esempio e come è stata ricavata la
risposta attesa, passo per passo, citando la regola della spec usata.

Chiavi di `expected.json` (tutte facoltative tranne `branches`):

```json
{
  "journey_name": "...",
  "activity_count": 5,
  "csv_tables": ["DE_Entry", "DE_Master"],
  "table_levels": {"DE_Master": "contact", "DE_Config": "scenario"},
  "branches": {
    "SPLIT-1/path_a": {"status": "covered"},
    "SPLIT-1/remainder_path": {"status": "not covered", "reason_contains": "unreachable"}
  },
  "scenario_count": {"min": 1, "max": 2},
  "case_count": {"min": 2, "max": 2},
  "contact_count": 6,
  "cases": [
    {"scenario_values": {"DE_Config.CHANNEL": "Email"},
     "contact_values": {"DE_Master.Perm": "True"},
     "end_activity": "EMAIL-1",
     "manual_actions": ["open"],
     "contact_count": 3}
  ],
  "unsupported": ["SOMETHING-1"],
  "warnings_contain": ["Email", "EMAIL"],
  "checks_pass": true,
  "settings": {"real_inbox": "tester@example.com", "case_insensitive_text": false}
}
```

`branches` deve elencare ogni outcome di ogni decision, engagement e random split (`"<activity key>/<outcome key>"`).
Un caso elencato deve esistere (valori confrontati come stringhe CSV; `end_activity` è l'ultima chiave di activity;
`manual_actions` è la lista ordinata dei tipi). `tests/test_examples.py` esegue ogni esempio nella
pipeline e confronta. Il pilota è `examples/pilot/` con `"package": "../../fixtures/CJ template complesso-v1.json"`.
