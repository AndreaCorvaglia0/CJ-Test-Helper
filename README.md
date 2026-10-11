# CJ Test Helper

CJ Test Helper legge l'export di un package di Salesforce Marketing Cloud, cioè il file JSON prodotto da Package Manager, e scrive dati di test che portano i contatti lungo ogni branch del customer journey. Scrive un CSV per ogni tabella letta dal journey, un elenco di scenari, un report di coverage e un testbook con il risultato atteso di ogni test. Non si collega mai a Salesforce: genera solo file e li controlla prima che vengano usati.

`docs/spec.md` è il riferimento per il comportamento dello strumento. Questo file spiega come avviarlo e come usare i file che produce.

## Requisiti e installazione

- Python 3.11 o successivo.
- I pacchetti elencati in `requirements.txt`:

```
pip install -r requirements.txt
```

## Avvio

Dalla cartella del repository:

```
python -m cjhelper "fixtures/CJ template complesso-v1.json" --out output --inbox name@example.com
```

Il comando stampa un riepilogo e l'esito di ogni trust check. Scrive tutti i file nella cartella di output, insieme a `test_data.zip`, che li contiene tutti. Sull'export del pilot impiega circa 30 secondi.

| Opzione | Cosa fa |
| --- | --- |
| `export` | L'export JSON del package. Obbligatoria. |
| `--out FOLDER` | Dove scrivere i file. Default `output`. |
| `--run-id R01` | Run identifier aggiunto a ogni chiave, come in `TST_R01_C0001`. Default `R01`. |
| `--inbox ADDRESS` | Inbox reale per i contatti che devono aprire o cliccare un'email. Default vuota. |
| `--phone NUMBER` | Numero di telefono reale. Nessuna attività supportata invia ancora messaggi a un telefono, quindi oggi non viene usato. Default vuoto. |
| `--contacts N` | Contatti per caso. Default 3. |
| `--random-contacts N` | Contatti nel caso statistico di un random split. Default 50. |
| `--case-insensitive` | I confronti di testo ignorano maiuscole e minuscole, quindi `Email` corrisponde a `EMAIL`. Default disattivata. |
| `--no-single-active` | Rende attivi tutti gli scenari nei CSV. Di default è attivo solo il primo. |
| `--time "YYYY-MM-DD HH:MM"` | Ora di generazione. Default l'ora corrente. Con la stessa ora si ottengono di nuovo gli stessi file. |
| `--no-testbook` | Non scrive `testbook.xlsx`. |

Il comando termina con codice 0 quando tutti i trust check sono superati e con codice 2 quando un check non è superato. In caso di errore, per esempio un file che non è un JSON valido o che non contiene un journey, stampa un solo messaggio, non scrive nulla e termina con codice 1.

## I file prodotti

| File | Contenuto |
| --- | --- |
| `<TableName>.csv` | Un file per ogni tabella letta dal journey o dalla entry query, con tutti gli scenari insieme, pronto da importare. UTF-8, separato da virgole, con i nomi esatti dei campi dello schema come intestazione, `True` e `False` per i Boolean e una cella vuota per il null. |
| `scenarios.csv` | Una riga per scenario: la chiave, l'ordine di esecuzione, quale scenario è attivo all'inizio, i casi e i contatti, e i valori a livello di scenario. |
| `report.md` | Da leggere per primo. Riepilogo, trust check, tabelle, come eseguire i test, scenari e casi, branch non coperti e perché, elementi non supportati, warning e pattern sospetti, assunzioni, impostazioni usate. |
| `testbook.xlsx` | Un test per caso nel formato del team: ID, Owner system, Test name, Description, Pre conditions, Detailed steps, Expected result, Status, Note. |
| `test_data.zip` | Tutti i file precedenti in un solo archivio. |

Termini usati in questi file:

- Un **branch** è un esito di uno split: decision split, engagement split o random split.
- Uno **scenario** è un insieme di valori a livello di scenario, per esempio una riga di una tabella di configurazione della campagna. Tutti i suoi contatti lo condividono.
- Un **caso** è un gruppo di contatti con gli stessi valori di contatto e le stesse azioni manuali, che quindi seguono lo stesso percorso. Ogni caso è un test del testbook. Di default ha 3 contatti.
- Un **caso statistico** copre i branch che seguono un random split. I suoi contatti non possono essere indirizzati su un branch preciso, quindi di default ha 50 contatti.

## Come un tester usa i file

1. Apri `report.md`. Verifica che tutti i trust check siano superati, poi leggi la sezione "Come eseguire i test".
2. Popola la tabella di ingresso a mano, con l'import diretto dei CSV: importa prima i CSV delle tabelle collegate e per ultimo il CSV di ingresso. Durante il test non si esegue nessuna automation.
3. Esegui uno scenario alla volta, in ordine di esecuzione. I CSV partono con il primo scenario attivo. Per rendere attivo uno scenario, imposta il campo di attivazione a True sulla riga dello scenario e a False su tutte le altre righe. Il report indica il campo: nel pilot è `ACTIVE` di `DE_NCRM_AD_HOC_CONFIG`. Il campo di attivazione è un filtro della entry query e nessuno split lo legge, quindi con l'import diretto non trattiene alcuno scenario.
4. Prima di passare allo scenario successivo, aspetta che i contatti dello scenario corrente siano usciti dal journey. Non cambiare altro e non reimportare nulla, perché il journey legge i dati degli split nel momento in cui un contatto raggiunge lo split.
5. Segui il testbook, una riga per caso. I passi indicano le attese, le eventuali azioni manuali con la loro scadenza e le evidenze da raccogliere. Confronta quello che vedi con l'Expected result.
6. Per una nuova generazione usa un nuovo run identifier. Le chiavi di un run precedente sono già nelle tabelle e un contatto di test non viene mai riutilizzato.

Assunzione da verificare al primo run reale: quando la entry source del journey è una data extension pianificata da un'automation, come nel pilot, Salesforce potrebbe richiedere il passo di ingresso nel journey di quell'automation perché i contatti importati entrino. Le righe da 23 a 27 di `docs/assumptions.md` spiegano il motivo.

### L'inbox reale

I contatti che devono aprire o cliccare un'email ricevono la tua inbox reale con plus-addressing. Con `--inbox name@example.com`, il contatto `TST_R01_C0004` riceve `name+TST_R01_C0004@example.com` e le sue email arrivano in `name@example.com`. Tutti gli altri contatti ricevono un indirizzo non recapitabile, `<contact key>@example.invalid`.

- Apri o clicca solo le email indicate dal testbook, e solo per i contatti di quel test.
- Fallo prima della scadenza indicata nel testbook. La scadenza è la fine del wait che precede l'engagement split, di default 24 ore dopo l'ora di generazione. Per questo motivo gli scenari con un'azione manuale vengono per primi nell'ordine di esecuzione.
- Se un run parte troppo tardi per rispettare una scadenza, genera di nuovo i dati.
- Senza `--inbox` la generazione funziona comunque. Quei contatti ricevono indirizzi non recapitabili e i branch che richiedono un open o un click risultano non coperti.

Un click si può chiedere solo se l'email contiene un link. Nel pilot l'email non ne ha, quindi i branch del click risultano non coperti.

### Il caso del random split

Un random split non si può forzare. I suoi branch ricevono un caso statistico, di default con 50 contatti, e il testbook indica l'intervallo accettato per il lato più piccolo. Per uno split 90/10, da 1 a 9 dei 50 contatti dovrebbero prendere il lato del 10%. Questo vale in circa il 97% dei run, quindi un conteggio fuori dall'intervallo può capitare per caso.

## Trust check

Dopo aver scritto i file, il generatore li rilegge e li controlla. Il report riporta l'esito di ogni check e i relativi dettagli.

| Check | Se non è superato |
| --- | --- |
| I valori rispettano tipo, lunghezza, nullability e primary key | L'import potrebbe scartare righe o troncare valori. |
| Ogni chiave trova corrispondenza tra le tabelle | Alcuni contatti non troverebbero la riga del loro scenario o le loro righe in una tabella collegata, quindi i loro split non vedrebbero i valori previsti. |
| Le righe di ingresso corrispondono alla entry query | Il CSV di ingresso non contiene quello che la entry query costruirebbe dagli altri CSV. |
| Ogni contatto, ri-simulato a partire dai file, segue il percorso previsto | Il risultato atteso nel testbook potrebbe essere sbagliato per alcuni contatti. |
| Ogni branch raggiungibile è coperto e ogni branch non coperto ha un motivo | La coverage indicata nel report non è affidabile. |
| Solo i contatti con un'azione manuale usano l'inbox reale; tutti gli altri sono non recapitabili | Alcune email potrebbero arrivare all'inbox reale quando non dovrebbero. |
| Due run con lo stesso input producono gli stessi file | Lo stesso export con le stesse impostazioni non darebbe gli stessi dati. |

Quando un check non è superato, il comando termina con codice 2 e il report elenca i problemi. Non importare i file finché il problema non è chiarito.

## Impostazioni e default

Queste sono le impostazioni della spec. La riga di comando usa i default e le opzioni descritte sopra ne modificano alcuni. Il report termina con le impostazioni usate per il run.

| Impostazione | Default | Opzione |
| --- | --- | --- |
| Contatti per caso | 3 | `--contacts` |
| Contatti per caso di random split | 50 | `--random-contacts` |
| Inbox reale per i test di open e click | Vuota | `--inbox` |
| Numero di telefono reale | Vuoto | `--phone` |
| Numero di telefono fittizio | `333333333333` | nessuna |
| Durata della finestra di validità | Da ieri a 7 giorni dopo | nessuna |
| Offset della data di wait | 0 ore | nessuna |
| Offset della data di wait prima di un engagement split | 24 ore | nessuna |
| Formato delle date nei CSV | `YYYY-MM-DD HH:MM` | nessuna |
| Un solo scenario attivo alla volta | Attivo quando viene rilevato un campo di attivazione | `--no-single-active` lo disattiva |
| Campo di attivazione | Suggerito dai filtri della entry query | nessuna |
| Run identifier nelle chiavi | R01 | `--run-id` |
| I confronti di testo ignorano maiuscole e minuscole | Disattivato | `--case-insensitive` |

## Come vengono scelti i valori

Ogni valore viene dalla prima di queste regole che si applica:

1. Un campo chiave o di join riceve una chiave generata, uguale in tutte le tabelle che fanno join su quel campo: `TST_R01_C0001` per i contatti, `TST_R01_S01` per gli scenari.
2. Un campo letto da uno split riceve il valore che serve al caso, scritto esattamente come nella condizione, con le stesse maiuscole e minuscole.
3. Un campo filtrato dalla entry query riceve un valore che supera il filtro, così il contatto entra davvero nel journey.
4. Un indirizzo email riceve l'inbox reale o `@example.invalid`, come descritto sopra. Un telefono riceve il numero fittizio. La finestra di validità va da ieri a 7 giorni dopo. Una data di wait è l'ora di generazione, per far terminare subito il wait, oppure 24 ore dopo quando i contatti devono aprire un'email dopo quel wait.
5. Ogni altro campo riceve un segnaposto: per il testo `TST_<field>_<n>` troncato alla lunghezza del campo, per i Boolean il loro default o False.

## Limiti noti

- Coverage dei branch, non dei percorsi: ogni branch viene attraversato almeno una volta, ma non ogni combinazione di branch.
- I random split sono coperti in modo statistico, mai con certezza.
- Vengono interpretati solo i tipi di attività, gli operatori e i pattern SQL supportati. Tutto il resto viene elencato nel report e i branch che ne dipendono risultano non coperti. Nulla viene dedotto per supposizione.
- I criteri di ingresso definiti fuori dal JSON, come i filtri sui contatti impostati nell'interfaccia e non esportati, non sono visibili.
- Il contenuto delle email e la personalizzazione non vengono testati. Lo strumento testa l'instradamento dei contatti.

Supportato nel PoC:

- Attività: decision split, engagement split, random split, wait by duration, wait by attribute, send-time wait, email, update contact.
- Operatori nelle condizioni: `Is`, `Equal` e `IsNull`, più `NotEqual`, `IsNotNull`, `GreaterThan`, `GreaterThanOrEqual`, `LessThan`, `LessThanOrEqual`, `Contains`, `BeginsWith` e `EndsWith`, ripresi dallo strumento precedente.
- SQL nelle entry query: nomi di tabella, uguaglianze di join, filtri WHERE semplici su uguaglianza, null e intervalli di date, ed espressioni semplici nella select. Un filtro o un'espressione più complessi vengono segnalati, e una colonna di ingresso che ne dipende riceve un segnaposto.

## Assunzioni da verificare

In alcuni punti i risultati attesi dipendono da comportamenti di Salesforce che la spec non chiarisce: le maiuscole e minuscole nei confronti di testo, come viene letta una data di wait senza fuso orario, come entrano i contatti quando l'ingresso è pianificato da un'automation, e altro. Ognuno è un'assunzione da verificare una volta con un piccolo run reale, mai un dato di fatto.

- `docs/assumptions.md` le elenca tutte, con la documentazione trovata e come verificare ciascuna, e pianifica un run di verifica di un giorno. Inizia dalla sezione "Check these first".
- La sezione "Assunzioni" di `report.md` elenca quelle che valgono per l'export eseguito.

## L'app a pagina singola

L'app a pagina singola è un passo successivo, la priorità 5 della spec: carica l'export, verifica cosa è stato rilevato, modifica le impostazioni, genera e scarica lo zip. Una prima versione è in `cjhelper/app.py` e si avvia con `streamlit run cjhelper/app.py` dalla cartella del repository. Finché non viene confermata, usa la riga di comando.

L'interfaccia, i messaggi del generatore (warning, trust check, errori di lettura) e i testi dei file scaricati sono in italiano; restano in inglese i termini d'uso comune del team, i nomi dei file e le intestazioni di colonna di scenarios.csv e del testbook (vedi docs/brand.md, "Glossario").

## Per gli sviluppatori

| Percorso | Contenuto |
| --- | --- |
| `docs/spec.md` | La specifica, il riferimento |
| `docs/plan.md` | Come la spec è suddivisa in moduli |
| `docs/progress.md` | Stato del lavoro e domande aperte |
| `docs/assumptions.md` | La review Salesforce: assunzioni da verificare e pattern sospetti |
| `cjhelper/` | Il generatore, un modulo per ogni passo della spec |
| `tests/` | Test unitari per modulo, gli esempi e il test end-to-end sul pilot |
| `examples/` | Piccoli journey costruiti a mano con le risposte attese |
| `fixtures/` | L'export del pilot |

Esegui i test con `python -m pytest`. I test sul pilot impiegano circa un minuto.
