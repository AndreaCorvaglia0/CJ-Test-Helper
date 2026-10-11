# Report finale: CJ Test Helper PoC

11 ottobre 2026, sera. Branch `claude/dazzling-ramanujan-l38jta`, sopra il main dopo il merge (PR #1 più il brand Lutech e la pagina in italiano). Per riprendere il lavoro, partire da `docs/progress.md`. Il report include le decisioni prese dall'utente in serata.

## Cosa passa

Sull'export pilota (`fixtures/CJ template complesso-v1.json`), con le impostazioni di default più un'inbox reale:

- Il journey `CJ_SkYDE_NCRM_Demo_final` viene letto con le sue 178 attività. Vengono prodotti esattamente quattro CSV (Entry, Master, Target, Config).
- Ogni CSV ha le colonne del suo schema, chiavi primarie univoche e valori che rispettano tipo e lunghezza. Ogni riga di Target fa join con una riga di Master e con una riga di Config. Ogni riga di Entry è quella che la entry query produrrebbe dagli altri tre CSV.
- Ogni branch raggiungibile dei 106 decision split è coperto da un caso di 3 contatti. Il random split 90/10 ha un caso statistico di 50 contatti con intervallo accettato da 1 a 9.
- I quattro branch Yes degli engagement split dopo i canali 2 e 3 sono segnalati come non raggiungibili. I tre contatti che devono aprire un'email usano l'inbox reale con plus-addressing; gli altri 143 usano `@example.invalid`.
- `testbook.xlsx` ha un test per caso e nomina ogni contatto; i totali di `report.md` corrispondono ai file. Due run con le stesse impostazioni producono file identici.
- Tutti e sette i trust check sono superati, compresa una simulazione dai file, indipendente, di ogni contatto. Un secondo test engineer, nuovo al progetto, ha confermato lo stesso risultato con un proprio simulatore, senza usare codice del package.
- Passano 39 esempi ricavati a mano (17 dal primo test engineer, 22 dal secondo). La suite di unit test conta circa 700 test, tra cui 18 che forniscono dati errati a ogni trust check (ogni check non è superato sulla mutazione che deve intercettare).
- L'app Streamlit di una pagina funziona dall'inizio alla fine (caricamento, revisione, impostazioni, generazione, download); una revisione UX l'ha approvata con modifiche, che sono state applicate.

Run di default sul pilota: 23 scenari, 33 casi, 146 contatti; 120 branch coperti, 2 coperti con azione manuale, 137 non coperti. Con confronti di testo che non distinguono maiuscole e minuscole: 41 scenari (i 40 dello strumento precedente più 1), 59 casi, 224 contatti, 91 branch non coperti.

## Fatto nell'ultimo passo (dopo il merge di main)

- Correzioni dei rilievi della review: viene seguita ogni query che popola la tabella di ingresso, non solo l'ultima (una query di post-elaborazione non nasconde più la vera entry query); i trust check leggono i file scritti e seguono i collegamenti agli scenari invece di fidarsi degli oggetti in memoria (un contatto ricollegato, duplicato, eliminato o aggiunto in un CSV ora fa fallire un check); le date devono essere scritte nel formato configurato; il check sulla entry query riconosce la forma di esclusione con LEFT JOIN; un engagement split con un tipo di statistica sconosciuto non rivendica nessun branch; i warning del parser riportano il prefisso della query una sola volta.
- Italiano: i messaggi del generatore (warning, pattern sospetti, motivi di non supporto, nomi e dettagli dei trust check, errori del loader, riga di comando) e i testi di `report.md` e `testbook.xlsx` sono in italiano, secondo il glossario di `docs/brand.md`. Restano in inglese i nomi dei file, le intestazioni di colonna di `scenarios.csv` e del testbook, gli identificatori dell'export e i valori generati. L'aspetto della pagina che viene da main non è stato toccato.
- Lingua, decisione dell'utente: tutto in italiano, cioè pagina, messaggi del generatore, file scaricati e documenti; in inglese restano solo i termini del team e gli identificatori. Questo report e `docs/assumptions.md` sono ora in italiano. `docs/spec.md` resta per ora in inglese come fonte di verità; il lead ha chiesto all'utente se tradurlo. Le docstring sono ancora in inglese.
- Rimandato, fuori dal pilota: i wait e le condizioni su Journey Data sono segnalati come warning ma non mappati su una tabella (RB-1/RB-10); i criteri di filtro della entry source impostati nella definizione dell'evento non vengono letti (RB-2); il check sull'inbox reale accetta qualsiasi parte locale prima di `+key@` (CK-9); i rilievi di gravità bassa della review (elencati nel triage dello scratchpad, vedi `docs/progress.md`).

## Cosa non passa, o si discosta dal testo della specifica

- "The PoC should land in the same range" dello strumento precedente (148 casi, 494 contatti): non soddisfatto, per scelta. Il generatore sceglie il minor numero di scenari e poi il minor numero di casi che attraversano ogni branch (33 casi). Aggiungere ogni classe di contatti a ogni scenario scelto darebbe circa 180 casi. Decisione dell'utente: la lettura minima è confermata (meno scenari possibile, poi meno casi possibile che coprono ogni branch; 33 casi sul pilota). Il punto non è più aperto.
- La motivazione di accettazione che la specifica dà per gli engagement split dopo i canali 2 e 3 ("because all six engagement splits reference the first email") vale solo quando i confronti di testo non distinguono maiuscole e minuscole. Con il confronto di default, che le distingue, quegli split diventano non raggiungibili prima, perché `CHANNEL2 Equal 'EMAIL'` non può mai essere vero su un percorso in cui `CHANNEL2 Equal 'Email'` è risultato vero. Il report riporta entrambe le cose: la causa a monte di ogni branch non raggiungibile e il pattern sospetto per cui gli split misurano un'email più vecchia dell'ultima inviata.
- Maiuscole e minuscole: la questione resta aperta. L'utente aspetta la documentazione di Salesforce prima di decidere il default. Fino ad allora il default resta quello della specifica: il confronto distingue maiuscole e minuscole.
- I journey con moltissimi campi a livello di contatto letti dagli split (più di circa un milione di combinazioni di valori) o con più di 400.000 percorsi distinti non vengono esplorati per intero; in quel caso il check di coverage non è superato e lo dice, invece di dichiarare una coverage che non c'è.
- `RUN_TIME` nella tabella Config del pilota resta vuoto invece di contenere l'ora di generazione (la regola della specifica per le altre date), perché la query di aggiornamento della configurazione dell'automation legge `WHERE RUN_TIME IS NULL`.
- La data del wait prima di un engagement split riceve l'offset di 24 ore solo quando un caso di quello scenario richiede davvero un'open o un click; secondo la lettera della specifica l'offset andrebbe aggiunto a ogni wait sul percorso verso un engagement split.
- Sui due punti precedenti l'utente osserva che sono specifici di questo journey, non comportamenti generali. Nessuno dei due è scritto nel codice per il pilota. Il primo deriva da una regola generale: alle righe generate si applicano i filtri delle query dell'automation che seguono la entry query, quindi un campo che una query legge come `IS NULL` resta vuoto. Il secondo deriva da una lettura generale della regola della specifica: l'offset si aggiunge dove un'open o un click devono avvenire davvero. Su un altro journey senza questi elementi nessuno dei due compare.

## Correzioni alla specifica suggerite dalla review Salesforce (`docs/assumptions.md`)

- Procedura di ingresso, decisione dell'utente: il dataset popola a mano la tabella di ingresso, con l'import diretto dei CSV e il CSV di ingresso per ultimo; durante il test non viene eseguita nessuna automation. Il report e il testbook prodotti dal generatore sono in corso di modifica, da parte di un altro agente, per descrivere solo l'import diretto. Il punto della review Salesforce resta un'assunzione da verificare al primo run reale: con una entry source di tipo data extension pianificata da un'automation, i contatti potrebbero essere ammessi solo quando l'automation viene eseguita, e quindi l'import del solo CSV di ingresso potrebbe non far entrare nessuno.
- Il valore di default della data del wait (ora di generazione, "so the wait ends at once") non è garantito se Salesforce legge la data del CSV in un altro fuso orario; un offset negativo sul wait è più sicuro. L'impostazione resta al valore di default della specifica.
- Tutte e sette le data extension dell'export hanno una retention policy; se è attiva nella business unit di test, le righe spariscono durante il run.

## Assunzioni Salesforce ancora da verificare

`docs/assumptions.md` ne elenca 35, con un piano di verifica di un giorno (3 righe di Config, 7 contatti). In testa le sei della specifica; tra quelle aggiunte, le più rilevanti: come entrano i contatti (righe da 23 a 27, la prima cosa da verificare), maiuscole e minuscole (riga 2, sposta 46 branch), retention (riga 32), un Boolean vuoto confrontato con `Is false` (riga 7), le open su un'email senza elemento di tracciamento delle open (riga 15), il fuso orario delle date dei wait (riga 6).

## Letture di progetto adottate (non assunzioni Salesforce)

- Meno scenari possibile, poi meno casi possibile al loro interno; l'utente ha confermato questa lettura. Le classi di contatti raggruppano le combinazioni di valori a livello di contatto in base al valore di verità di ogni formula di branch che dipende solo da campi a livello di contatto (8 sul pilota).
- Un campo letto da uno split e fissato da un filtro della entry query, da un'espressione letterale nella SELECT o dalla chiave generata assume solo quel valore; gli altri branch sono segnalati come non raggiungibili, con il motivo.
- Un operatore o un campo sconosciuto rende non supportato solo quel branch; i branch precedenti restano copribili. Il remainder viene valutato per ultimo, qualunque sia la sua posizione.
- Uno split che legge il campo dell'indirizzo fissa l'indirizzo; un'open o un click in un caso del genere è segnalato come non coperto, ma il caso esiste comunque.
- Due engagement split sullo stesso percorso ricevono offset di wait cumulativi.

## Limiti noti

Coverage dei branch, non dei percorsi. I random split sono coperti in modo statistico. Il generatore comprende solo i tipi di attività, gli operatori e le forme SQL elencati; il resto viene segnalato. I criteri di ingresso impostati fuori dall'export non sono visibili. Il contenuto delle email non viene testato.

## Dove si trovano le cose

- Codice: `cjhelper/` (model, loader, criteria, sqlparse_lite, tables, graph, coverage, datagen, checks, outputs, pipeline, app). Riga di comando: `python -m cjhelper <export> --out <dir> --inbox <address>`. Pagina: `streamlit run cjhelper/app.py`.
- Documenti: `README.md`, `docs/spec.md`, `docs/plan.md`, `docs/export-format.md`, `docs/assumptions.md`, `docs/ux-review.md`, `docs/progress.md`.
- Esempi: `examples/<name>/` con `package.json`, `expected.json`, `README.md`; li esegue `tests/test_examples.py`.
