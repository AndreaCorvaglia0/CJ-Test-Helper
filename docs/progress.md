# Avanzamento

Si riparte da questo file. Spec: `docs/spec.md`. Contratto: `docs/plan.md`.

## Fatto

- Repository impostato: spec copiata in `docs/spec.md`, export pilota in `fixtures/`, vecchio tool conservato solo nella storia di git (commit 83f0f65) come riferimento.
- `cjhelper/model.py`: il modello dati condiviso e il contratto dei moduli.
- `docs/plan.md`: responsabilità dei moduli e firme delle funzioni. `docs/export-format.md`: forma dell'export per gli esempi fatti a mano.

- `loader.py` + `criteria.py` (197 test), `sqlparse_lite.py` (144 test), `tables.py` (27 test): consegnati e rivisti.
- `graph.py`, `coverage.py`, `checks.py`, `pipeline.py`, `__main__.py` (lead): la prima esecuzione integrata sul pilota supera tutti i 7 trust check.
  `python -m cjhelper "fixtures/CJ template complesso-v1.json" --out output --inbox tester@example.com` richiede circa 30 s.

- `datagen.py` + `outputs.py` (88 test): consegnati. L'intera suite (562 test) passa.
- `examples/`: 17 esempi con risposte attese ricavate a mano (15 piccoli, 2 varianti del pilota con conteggi minimi dimostrati a mano);
  tutti passano in `tests/test_examples.py`. Problemi trovati nel ciclo e corretti: il controllo di coverage leggeva male lo stato voluto "nessuna inbox reale";
  un operatore di condizione sconosciuto bloccava la run (ora lo split è non supportato e i suoi branch non coperti); una condizione su un campo
  assente dallo schema veniva interpretata come testo (ora è non supportata); un campo fissato da un filtro di ingresso non viene più provato con altri valori.
- `docs/assumptions.md`: revisione Salesforce, 35 assunzioni da verificare, 16 pattern sospetti, un piano di run di verifica di un giorno.
  Recepito: i filtri delle query dell'automation seguita sono applicati alle righe generate (RUN_TIME resta vuoto).

- Technical writer: README.md, report.md con una sezione su come eseguire i test e il raggruppamento per cause a monte, testo del testbook. Fatto.
- Pagina Streamlit `cjhelper/app.py` (28 test), screenshot giudicati dal lead; revisione UX fatta.
- Ciclo di revisione di fine livello, parte 1 (revisori di coverage e di generazione dei dati, 34 finding): corretti in tre lotti, vedi i
  commit "Review fixes, batch 1/2/3". In sintesi: valori 'other' che rispettano la lunghezza, campi email e phone letti dagli split, campi
  chiave letti dagli split, outcome non supportati invece di split interi, remainder valutato per ultimo, random split annidati,
  casi statistici con azioni manuali, branch prima di un random split, SELECT * con elementi extra, NULL nella select,
  token di data .NET non supportati, colonne di ingresso copiate da colonne a livello di scenario, i wait prima dell'email non ricevono tempo extra,
  placeholder univoci per le chiavi primarie, chiavi del contatto di tipo email, colonne `active_at_start` e `activation_field` in scenarios.csv.

## Piano residuo

Niente in programma. Possibili passi successivi, da decidere con l'utente: verificare le assunzioni su Salesforce con una piccola run reale
(docs/assumptions.md), i finding rimandati qui sotto, le letture di design ancora aperte (docs/final-report.md).

Decisioni prese dall'utente la sera dell'11 ottobre:

- Il conteggio minimo dei casi è confermato: prima il minor numero di scenari, poi il minor numero di casi.
- Il default per maiuscole e minuscole resta quello che le distingue (case-sensitive), finché l'utente non ha letto la documentazione di Salesforce.
- Tutto è in italiano, tranne i termini inglesi del team e gli identificatori. `docs/spec.md` resta in inglese per ora.
- La procedura di ingresso è l'import diretto dei CSV (durante il test non si esegue nessuna automation). Un altro agente la sta applicando a report e testbook.

Fatto la sera dell'11 ottobre: traduzione in italiano dei messaggi del generatore e dei file prodotti (quattro agenti Opus su moduli
disgiunti, glossario in docs/brand.md "Glossario"; pattern in outputs.py riallineati ai nuovi testi; un unico
prefisso "pattern sospetto:"), tests/test_checks.py (18 test), RB-5, RB-15 (prefisso unico delle query). La suite veloce (~700 test),
i 39 esempi e il test di accettazione del pilota passano; la run da riga di comando sul pilota dà 7/7 check, 23/33/146 come prima.

Finding rimandati (non nel pilota): RB-1/RB-10 (mappatura di Journey Data wait e condizioni), RB-2 (warning sui criteria della entry source),
CK-9 (la parte locale dell'inbox non è controllata); tutti i finding bassi del triage.
Instradamento: Opus per il codice e il testo italiano, Sonnet per i controlli e il lavoro meccanico, Haiku per i compiti banali.

## Stato dopo il merge della PR #1 (upstream main)

- PR #1 unita; upstream ha aggiunto su main: brand Lutech (tema, Montserrat, logo, docs/brand.md), pagina in italiano con
  stepper e card dei step comprimibili (cjhelper/app.css), README in italiano, sezione di CLAUDE.md su aspetto e lingua.
  Sono cambiati solo cjhelper/app.py, app.css, config.toml, README.md, tests/test_app.py, docs/brand.md e gli asset: nessuna sovrapposizione con
  il generatore. Il branch è stato portato avanti in fast-forward su main; l'aspetto della pagina non va cambiato.
- Correzioni del triage committate sopra (4e5e01a): ogni query che popola la tabella di ingresso viene seguita (RB-4/CP-4), forma di esclusione
  con LEFT JOIN nel controllo di ingresso (RB-13), i trust check leggono i file e seguono i collegamenti degli scenari (CK-1, CK-4, CK-5, CK-6, CK-8,
  CK-11, CK-12). CK-18 (tests/test_checks.py) e RB-5 (statsTypeId sconosciuto: entrambi i branch non coperti) fatti con la traduzione.

## Regole di lavoro dell'utente

- Subagent su Opus con effort massimo per il lavoro che richiede giudizio; Sonnet per compiti più semplici, anche lunghi, supervisionati, e per i controlli semplici.

## Letture di design del lead (non assunzioni su Salesforce)

- Casi dentro uno scenario: la spec chiede "the smallest set of paths that crosses every branch" e "the fewest scenarios".
  Il generatore sceglie il minor numero di scenari, poi il minor numero di casi al loro interno (un secondo passo greedy). Non aggiunge ogni
  classe di contatti a ogni scenario. Sul pilota dà 23 scenari / 33 casi / 146 contatti (distingue maiuscole e minuscole) e
  41 / 59 / 224 (non distingue maiuscole e minuscole); il tool precedente riportava 41 / 148 / 494. Il numero di scenari coincide, il numero di casi è inferiore
  per scelta di design. Da confermare con l'utente.
- Le classi di contatti raggruppano le combinazioni di valori a livello di contatto in base alla verità di ogni formula di outcome puramente a livello di contatto (e di ogni
  condizione a livello di contatto di una formula mista): 8 classi sul pilota, come dice la spec.
- Il valore di testo "other" è `OTHER` (oppure `OTHER_2`, ... quando è già preso); i Boolean prendono sempre entrambi i valori; null viene aggiunto quando lo schema lo ammette.
- Caso statistico: gli engagement split a valle del random split prendono il branch No (in un caso statistico non è richiesta nessuna azione manuale).

## Prossimi passi

- Vedi "Piano residuo" sopra. Dopo: consegna con il report finale; le assunzioni in docs/assumptions.md restano da
  verificare con una piccola run reale.

## Da riferire all'utente (correzioni alla spec suggerite dalla revisione Salesforce, non cambiate nel codice)

- Procedura di ingresso: la revisione dice che importare solo il CSV di ingresso non fa entrare nessuno; l'automation (con il suo step di ingresso nel journey) deve girare,
  e una run completa esegue anche la entry query (duplicando le righe di ingresso) e lo step di verifica. La spec presenta l'import diretto
  come via normale. Il generatore scrive comunque tutti e quattro i CSV, quindi entrambe le procedure sono possibili; il report le elenca come alternative.
- Date dei wait: il default della spec (ora di generazione, "so the wait ends at once") non è garantito se Salesforce legge la data del CSV in
  un altro fuso orario (CST); un'attesa con offset negativo sarebbe più sicura. L'impostazione resta al default della spec.
- Le maiuscole e minuscole spostano 46 branch tra coperti e non coperti sul pilota; il default dell'impostazione (distingue maiuscole e minuscole) è quello della spec.

## Domande aperte

- Pilota con il confronto di default che distingue maiuscole e minuscole: 137 dei 259 branch degli split non sono raggiungibili perché `CHANNEL2 Equal 'EMAIL'` /
  `CHANNEL3 Equal 'EMAIL'` non possono mai essere veri sui percorsi che hanno già superato `CHANNEL2 Equal 'Email'`. La riga di accettazione della spec dice che i
  quattro branch Yes degli engagement split dopo i channel 2 e 3 non sono raggiungibili "because all six engagement splits reference the first email";
  questo è il motivo solo quando i confronti di testo non distinguono maiuscole e minuscole (allora 91 branch restano non raggiungibili). Le due letture danno lo stesso stato.
- `RUN_TIME` (Date che ammette null, senza condizione né filtro della entry query) resta vuoto, e non riceve l'ora di generazione prevista dalla regola della spec per gli "altri campi data";
  la query di aggiornamento della config filtra `WHERE RUN_TIME IS NULL`, quindi il generatore lo lascia vuoto. Questo differisce dalla regola della spec.

## Fatti verificati sull'export pilota

- 178 attività: 106 decision split, 34 update contact, 13 wait (3 by attribute su Config.WAIT1-3, 10 by duration di 1 minuto), 11 email (tutte lo stesso asset "Demo Sky", senza link), 7 send-time wait, 6 engagement split (tutti riferiti a EMAILV2-1), 1 random split 90/10.
- Attività iniziale: `MULTICRITERIADECISIONV2-1` (Control Group Required). Tutte le 178 attività sono raggiungibili per struttura.
- La entry query collega con join Master -> Target su `ContactId = SalesforceId` e Target -> Config su `Description = CampaignName`; filtri `C.active = 'True'`, `HAS_RUN = 'False'`, intervallo di date su `START_DATE`/`END_DATE`.
- Con il confronto di default che distingue maiuscole e minuscole, `CHANNEL2 Equal 'EMAIL'` (controllo email del channel 2) non può mai essere vero su un percorso che l'ha raggiunto tramite `CHANNEL2 Equal 'Email'`, quindi gli engagement split dei channel 2 e 3 non sono raggiungibili del tutto; i loro branch Yes non sono comunque raggiungibili perché EMAILV2-1 viene inviata solo quando CHANNEL1 è Email, che instrada verso l'engagement split del channel 1.
