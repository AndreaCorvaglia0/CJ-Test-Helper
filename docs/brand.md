# Brand e stile dell'interfaccia

Regole di stile per la pagina Streamlit e per ogni interfaccia futura del progetto. Chi modifica l'aspetto della pagina, persona o agente, parte da qui: lo stile è solo presentazione e non cambia mai la logica di generazione, le impostazioni o i file prodotti. La fonte è il documento "Lutech Brand Guidelines" (gennaio 2024); i numeri tra parentesi sono i capitoli di quel documento. Il PDF originale non è nella repository: le regole che servono a questo progetto sono riportate qui.

Dove questo file prende una decisione che le linee guida non coprono (gli stati, i grigi chiari, il peso del testo a schermo), lo dice esplicitamente.

## Dove sono applicate

| File | Cosa contiene |
| --- | --- |
| `.streamlit/config.toml` | Tema: colori, font, raggi, colori degli stati |
| `cjhelper/app.css` | Header, stepper, card degli step, tabelle, banner e riepilogo numerico. Non deve contenere il carattere "minore di", nemmeno nei commenti: il sanitizer HTML di Streamlit scarterebbe l'intero foglio di stile |
| `cjhelper/static/fonts/` | Montserrat in WOFF2 (pesi 300, 400, 500, 600, 700) e la licenza `OFL.txt` |
| `cjhelper/static/lutech-logo.svg` | Logo in versione primaria, per fondi chiari |
| `cjhelper/static/lutech-pictogram.svg` | Solo pittogramma (1.5.1), per l'icona della scheda del browser |
| `assets/brand/` | File originali forniti: logo RGB per fondi scuri, logo CMYK, logo con claim |

La pagina va avviata dalla cartella del repository (`streamlit run cjhelper/app.py`), altrimenti Streamlit non legge `config.toml` e la pagina perde tema e font.

## Logo

- Versione primaria (1.4.1): pittogramma Crimson Glory, logotipo Jet, su fondo chiaro. È quella da usare sempre in questa app (`cjhelper/static/lutech-logo.svg`).
- Versione secondaria (1.4.2): pittogramma Crimson, logotipo bianco, solo su fondi scuri (`assets/brand/lutech-logo-RGB-WhiteCrimson.svg`).
- Larghezza minima a schermo: 90 px per il logo completo, 30 px per il solo pittogramma (1.7).
- Area di rispetto (1.6): attorno al logo resta libero uno spazio pari almeno al braccio inferiore della E. In pratica, nell'header non ci sono altri elementi a meno di 16 px dal logo.
- Non consentito (1.9): cambiare i colori, deformare le proporzioni, ruotare, spostare il pittogramma rispetto al logotipo, usarlo su sfondi che ne riducono la leggibilità, aggiungere effetti (ombre, glow), riscrivere il logotipo con un altro font.

Il file SVG RGB fornito usa `#C01637` per il pittogramma; la versione primaria nella repository usa il valore HEX ufficiale `#BE0036` (1.8.1). I tracciati sono gli stessi del file fornito.

## Colori

### Palette primaria (1.8.1)

| Nome | HEX | Uso nell'interfaccia |
| --- | --- | --- |
| Crimson Glory | `#BE0036` | Azione principale (un solo pulsante primario per vista), step attivo, linea sotto l'header, link |
| Jet | `#333333` | Testo, step completati, intestazioni |

### Palette ausiliaria (1.8.2)

| HEX | Uso nell'interfaccia |
| --- | --- |
| `#570A19` | Non usato a schermo |
| `#8C0031` | Hover del pulsante primario, testo degli errori |
| `#E81B44` | Non usato: troppo vicino al Crimson per distinguersi |
| `#444444` | Testo secondario (etichette, didascalie) |
| `#B4B4B4` | Bordi dei campi, testo disattivato |
| `#E1E3EA` | Bordi delle card e delle tabelle, separatori |

Decisione di progetto: `#F6F7FA`, una tinta più chiara di `#E1E3EA`, è lo sfondo delle intestazioni di tabella e dei campi. Le linee guida non hanno un grigio così chiaro e a schermo `#E1E3EA` come sfondo pesa troppo.

### Stati

Le linee guida non hanno un verde. Gli stati usano la palette secondaria (1.8.3):

| Stato | Colore | Sfondo |
| --- | --- | --- |
| Superato, completato | `#335A66` | `#E8F0F3` |
| Warning | testo `#5E5400` | `#F5EFC0` |
| Errore, non superato | `#8C0031` | `#F9E5EA` |

Il giallo `#E5D352` non si usa mai come colore del testo su bianco: il contrasto è troppo basso. Si usa solo come sfondo o come bordo.

### Regole d'uso

- Il Crimson è un accento. Se compare ovunque smette di indicare dove cliccare: un solo pulsante primario per vista, nessun riempimento di grandi superfici.
- La palette terziaria (1.8.4) non si usa nell'app.
- Solo tema chiaro.

## Tipografia

- Font istituzionale (1.3.1): Montserrat, in tutti i testi dell'interfaccia.
- Le linee guida indicano il Light come base preferita. A 14 px su schermo il Light si legge male, quindi il testo corrente usa il Regular (400). Il Light (300) è riservato al nome dell'app e ai titoli grandi in maiuscolo, con spaziatura tra le lettere.
- Pesi usati: 300 per il display, 400 per il testo, 500 per i numeri dei riepiloghi, 600 per titoli di step ed etichette, 700 per le etichette in maiuscoletto.
- Il font Lutech (1.3.3), monopeso e solo maiuscolo, è previsto per titolazioni e grandi formati. Non è nella repository e non si usa nell'app. Se verrà aggiunto, solo per il nome dell'app, mai per testo corrente.
- Codice e nomi tecnici restano nel font monospace di Streamlit.

## Struttura della pagina

- Header bianco con logo, separatore verticale e nome dell'app in Montserrat Light maiuscolo; sotto, una linea Crimson di 3 px.
- Uno stepper orizzontale con i quattro step della spec: completato (linea Jet), attivo (linea Crimson), da fare (linea `#E1E3EA`).
- Ogni step è una card a scomparsa. Uno step completato si chiude e mostra nell'intestazione una riga di riepilogo, così l'intero percorso resta visibile in una schermata.
- Le anteprime dei CSV sono tabelle, una per file in schede separate, senza pulsante di download: il file completo è nello zip.
- Una colonna centrale larga al massimo circa 1080 px. Niente sidebar.

## Testi

- Lingua: italiano, tono da manuale o blog tecnico curato. Frasi brevi e dichiarative, niente slogan, niente punti esclamativi, niente emoji.
- Restano in inglese i termini d'uso comune nel lavoro su Marketing Cloud: journey, split, branch, decision split, engagement split, random split, wait, entry query, data extension, automation, inbox, open, click, trust check, warning, coverage, run, run identifier, testbook, report, CSV, Boolean.
- Sono in italiano: scenario, caso, contatto, tabella, campo, impostazioni, livello, ruolo.
- I nomi dei tipi di attività sono quelli dell'interfaccia di Salesforce (Decision split, Wait by duration, Update contact).
- Maiuscola solo a inizio frase o etichetta, anche nei titoli.
- Pulsanti con un verbo all'imperativo: "Genera", "Scarica lo zip".
- Anche i messaggi prodotti dal generatore (warning, nomi e dettagli dei trust check, errori del loader, messaggi della riga di comando) e i testi dei file scaricati (report.md, testbook.xlsx) sono in italiano e seguono le stesse regole e il glossario qui sotto. Restano in inglese i nomi dei file, le intestazioni di colonna di `scenarios.csv` e del testbook (il layout del team, con `Owner system` = `SFMC` e `Status` = `TO START`), i nomi di campi, tabelle, attività e query così come sono nell'export, e i valori generati (`OTHER`, `<generated key>`).

### Glossario

Stessa parola per lo stesso concetto, in tutta l'app e in tutti i file prodotti. Il plurale dei termini inglesi è invariato (i branch, gli split, i warning).

| Inglese | Nell'interfaccia e nei file |
| --- | --- |
| journey, activity type names (Decision split, Engagement split, Random split, Wait by duration, Wait by attribute, Send-time wait, Update contact, Email) | invariati, come nell'interfaccia di Salesforce |
| branch, split, path (of a split) | branch; "remainder" per l'ultimo path di un decision split, come in Salesforce |
| path (of a contact through the journey) | percorso |
| entry query, entry source, entry event | invariati |
| entry table | tabella di ingresso |
| data extension, automation, query, join, lookup, attribute set, relationship | data extension, automation, query, join, lookup, attribute set, relazione |
| field, table, value, key, primary key, contact key, scenario key | campo, tabella, valore, chiave, chiave primaria, chiave del contatto, chiave dello scenario |
| scenario-level, contact-level | a livello di scenario, a livello di contatto |
| scenario, case, contact, statistical case | scenario, caso, contatto, caso statistico |
| covered, not covered, covered with manual action | coperto, non coperto, coperto con azione manuale |
| reachable, unreachable, structurally unreachable | raggiungibile, non raggiungibile, non raggiungibile per struttura |
| behind (an uncovered branch) | a valle di |
| manual action, open, click, inbox, plus-addressing | azione manuale, open, click, inbox, plus-addressing |
| deadline, accepted range, expected delay | scadenza, intervallo accettato, attesa prevista |
| unsupported (element, operator, condition) | non supportato |
| suspicious pattern, warning, error | pattern sospetto, warning, errore |
| trust check, passed, failed | trust check, superato, non superato |
| coverage, report, testbook, run, run identifier, settings | coverage, report, testbook, run, run identifier, impostazioni |
| letter case, case-sensitive, case-insensitive | maiuscole e minuscole; distingue / non distingue maiuscole e minuscole |
| nullable, null, length, type, Boolean, Date, Text, Number | ammette null, null, lunghezza, tipo, Boolean, Date, Text, Number |
| generation time, wait date, written value | ora di generazione, data del wait, valore scritto |
| placeholder, export, package, zip, CSV, JSON, SQL | invariati |
| sendable field, subscriber key, send address | campo sendable, subscriber key, indirizzo di invio |
| evidence (collected during the test) | evidenze |
| re-simulation from the files | simulazione dai file |
| determinism (two runs give the same files) | determinismo |
