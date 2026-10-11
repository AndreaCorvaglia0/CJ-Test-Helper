# Brand e stile dell'interfaccia

Regole di stile per la pagina Streamlit e per ogni interfaccia futura del progetto. La fonte è il documento "Lutech Brand Guidelines" (gennaio 2024); i numeri tra parentesi sono i capitoli di quel documento. Il PDF originale non è nella repository: le regole che servono a questo progetto sono riportate qui.

Dove questo file prende una decisione che le linee guida non coprono (gli stati, i grigi chiari, il peso del testo a schermo), lo dice esplicitamente.

## Dove sono applicate

| File | Cosa contiene |
| --- | --- |
| `.streamlit/config.toml` | Tema: colori, font, raggi, colori degli stati |
| `cjhelper/static/fonts/` | Montserrat in WOFF2 (pesi 300, 400, 500, 600, 700) e la licenza `OFL.txt` |
| `cjhelper/static/lutech-logo.svg` | Logo in versione primaria, per fondi chiari |
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
- I messaggi prodotti dal generatore (warning, nomi dei trust check, errori del loader) e i file scaricati sono ancora in inglese; verranno tradotti in un passo successivo.
