# SFMC Data Views — Reference Completa

Le Data Views sono tabelle di sistema read-only in SFMC. Contengono gli ultimi **6 mesi** di dati di tracking.
Si interrogano con SQL in **Automation Studio → Query Activity** o **Query Studio**.

> ⚠️ I dati non sono in tempo reale. `_Click` può avere ritardi fino a 72h.
> Tutti i timestamp sono in **CST (Central Standard Time)**, DST non osservato.

---

## Indice

- [_Sent](#_sent)
- [_Job](#_job)
- [_Open](#_open)
- [_Click](#_click)
- [_Bounce](#_bounce)
- [_Unsubscribe](#_unsubscribe)
- [_Complaint](#_complaint)
- [_JourneyActivity](#_journeyactivity)
- [_Journey](#_journey)
- [_Subscribers](#_subscribers)
- [_ListSubscribers](#_listsubscribers)
- [_BusinessUnitUnsubscribes](#_businessunitunsubscribes)
- [_EnterpriseAttribute](#_enterpriseattribute)
- [Join patterns tra Data Views](#join-patterns)

---

## _Sent

Registra ogni invio email a livello subscriber+job. Una riga per ogni email inviata.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `AccountID` | int | ID account SFMC |
| `OYBAccountID` | int | ID "On Your Behalf" account (per reply mail management) |
| `JobID` | int | ID univoco dell'invio (join con `_Job`) |
| `ListID` | int | ID lista |
| `BatchID` | int | ID batch (per invii segmentati) |
| `SubscriberID` | int | ID interno subscriber (evitare come chiave di join) |
| `SubscriberKey` | nvarchar | Chiave subscriber preferita per i join |
| `EventDate` | datetime | Data/ora invio (CST) |
| `Domain` | nvarchar | Dominio email del destinatario |
| `TriggererSendDefinitionObjectID` | nvarchar | Collega a `_JourneyActivity.JourneyActivityObjectID` |
| `TriggeredSendCustomerKey` | nvarchar | Customer key della triggered send definition |

```sql
-- Tutti gli inviati degli ultimi 30 giorni
SELECT
    s.SubscriberKey,
    s.JobID,
    s.EventDate,
    s.Domain
FROM [_Sent] s
WHERE s.EventDate >= DATEADD(DAY, -30, GETDATE())
```

---

## _Job

Metadata degli invii: nome email, oggetto, from address. Da joinare con `_Sent` per arricchire il reporting.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `JobID` | int | PK — chiave di join con `_Sent`, `_Open`, `_Click`, `_Bounce` |
| `ParentJobID` | int | Utile per A/B test (varianti puntano al job padre) |
| `BatchID` | int | ID batch |
| `OriginalSchedTime` | datetime | Orario pianificato |
| `ActualSchedTime` | datetime | Orario effettivo di invio |
| `CompletedTime` | datetime | Orario di completamento |
| `JobStatus` | nvarchar | Stato: `Sent`, `Cancelled`, `Error`... |
| `EmailName` | nvarchar | Nome dell'email in Content Builder |
| `EmailSubject` | nvarchar | Oggetto dell'email |
| `EmailID` | int | ID email in Content Builder |
| `FromName` | nvarchar | Nome mittente |
| `FromEmail` | nvarchar | Email mittente |
| `SentCount` | int | Numero totale di invii del job |
| `DeliveredCount` | int | Numero stimato di consegnati |
| `UnsubscribeCount` | int | Disiscrizioni generate da questo job |
| `MissingCount` | int | Contatti non trovati |
| `BounceCount` | int | Bounce generati |
| `NotSentCount` | int | Non inviati (es. suppressioni) |
| `AccountUserID` | int | ID utente che ha schedulato l'invio (utile per audit log) |
| `SendDefinitionExternalKey` | nvarchar | External key della send definition |
| `SendClassification` | nvarchar | `Commercial` o `Transactional` |
| `IsWrapped` | bit | Se i link sono wrapped per il tracking |
| `SuppressTracking` | bit | Se il tracking è soppresso |

```sql
-- Metadata degli ultimi invii con nome email e oggetto
SELECT
    j.JobID,
    j.EmailName,
    j.EmailSubject,
    j.FromName,
    j.ActualSchedTime,
    j.SentCount,
    j.DeliveredCount,
    j.BounceCount
FROM [_Job] j
WHERE j.ActualSchedTime >= DATEADD(DAY, -90, GETDATE())
    AND j.JobStatus = 'Sent'
ORDER BY j.ActualSchedTime DESC
```

---

## _Open

Aperture email. Contiene duplicati (ogni apertura = una riga). Usare `IsUnique = 1` per le aperture uniche.

> ⚠️ Le aperture non sono affidabili al 100% (mail client privacy, pixel blocking). Usare come indicatore relativo, non assoluto.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `AccountID` | int | ID account |
| `OYBAccountID` | int | On Your Behalf account ID |
| `JobID` | int | Join con `_Job` |
| `ListID` | int | ID lista |
| `BatchID` | int | ID batch |
| `SubscriberID` | int | ID interno (evitare per join) |
| `SubscriberKey` | nvarchar | Chiave preferita |
| `EventDate` | datetime | Data/ora apertura (CST) |
| `Domain` | nvarchar | Dominio email |
| `IsUnique` | bit | `1` = prima apertura di questo subscriber per questo job |
| `TriggererSendDefinitionObjectID` | nvarchar | Collega a `_JourneyActivity` |

```sql
-- Open Rate per job (ultimi 30 giorni)
SELECT
    j.JobID,
    j.EmailName,
    j.EmailSubject,
    j.SentCount,
    COUNT(DISTINCT CASE WHEN o.IsUnique = 1 THEN o.SubscriberKey END) AS UniqueOpens,
    CAST(
        COUNT(DISTINCT CASE WHEN o.IsUnique = 1 THEN o.SubscriberKey END) * 100.0
        / NULLIF(j.SentCount, 0) AS DECIMAL(5,2)
    ) AS OpenRate_Pct
FROM [_Job] j
    LEFT JOIN [_Open] o ON j.JobID = o.JobID
WHERE j.ActualSchedTime >= DATEADD(DAY, -30, GETDATE())
    AND j.JobStatus = 'Sent'
GROUP BY j.JobID, j.EmailName, j.EmailSubject, j.SentCount
ORDER BY j.ActualSchedTime DESC
```

---

## _Click

Click sui link. Ogni click = una riga. `IsUnique = 1` per i click unici per subscriber+job.

> ⚠️ Ritardo possibile fino a 72h. Considerare nella schedulazione dei report.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `AccountID` | int | ID account |
| `OYBAccountID` | int | On Your Behalf account ID |
| `JobID` | int | Join con `_Job` |
| `ListID` | int | ID lista |
| `BatchID` | int | ID batch |
| `SubscriberID` | int | ID interno (evitare per join) |
| `SubscriberKey` | nvarchar | Chiave preferita |
| `EventDate` | datetime | Data/ora click (CST) |
| `Domain` | nvarchar | Dominio email |
| `URL` | nvarchar | URL cliccato |
| `LinkName` | nvarchar | Nome del link (se definito in Content Builder) |
| `LinkContent` | nvarchar | Testo ancora del link |
| `IsUnique` | bit | `1` = primo click di questo subscriber per questo job |
| `TriggererSendDefinitionObjectID` | nvarchar | Collega a `_JourneyActivity` |

```sql
-- CTR per job (click unici / inviati)
SELECT
    j.JobID,
    j.EmailName,
    j.SentCount,
    COUNT(DISTINCT CASE WHEN c.IsUnique = 1 THEN c.SubscriberKey END) AS UniqueClickers,
    CAST(
        COUNT(DISTINCT CASE WHEN c.IsUnique = 1 THEN c.SubscriberKey END) * 100.0
        / NULLIF(j.SentCount, 0) AS DECIMAL(5,2)
    ) AS CTR_Pct
FROM [_Job] j
    LEFT JOIN [_Click] c ON j.JobID = c.JobID
WHERE j.ActualSchedTime >= DATEADD(DAY, -30, GETDATE())
    AND j.JobStatus = 'Sent'
GROUP BY j.JobID, j.EmailName, j.SentCount
```

---

## _Bounce

Bounce email. Include sia hard che soft bounce con categoria e motivo SMTP.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `AccountID` | int | ID account |
| `OYBAccountID` | int | On Your Behalf |
| `JobID` | int | Join con `_Job` |
| `ListID` | int | ID lista |
| `BatchID` | int | ID batch |
| `SubscriberID` | int | ID interno |
| `SubscriberKey` | nvarchar | Chiave preferita |
| `EventDate` | datetime | Data/ora bounce (CST) |
| `Domain` | nvarchar | Dominio |
| `BounceCategoryID` | int | ID categoria bounce |
| `BounceCategory` | nvarchar | Es: `Hard bounce`, `Soft bounce`, `Technical` |
| `BounceSubcategoryID` | int | ID sottocategoria |
| `BounceSubcategory` | nvarchar | Dettaglio sottocategoria |
| `BounceTypeID` | int | ID tipo bounce |
| `BounceType` | nvarchar | `HardBounce` o `SoftBounce` |
| `SMTPBounceReason` | nvarchar | Messaggio SMTP grezzo |
| `SMTPMessage` | nvarchar | Messaggio SMTP completo |
| `SMTPCode` | int | Codice SMTP (es. 550, 421) |
| `IsFalseBounce` | bit | `1` se identificato come falso bounce |

```sql
-- Analisi bounce per categoria (ultimi 7 giorni)
SELECT
    b.BounceCategory,
    b.BounceSubcategory,
    b.BounceType,
    COUNT(*) AS BounceCount,
    COUNT(DISTINCT b.SubscriberKey) AS UniqueSubscribers
FROM [_Bounce] b
WHERE b.EventDate >= DATEADD(DAY, -7, GETDATE())
    AND b.IsFalseBounce = 0
GROUP BY b.BounceCategory, b.BounceSubcategory, b.BounceType
ORDER BY BounceCount DESC
```

---

## _Unsubscribe

Disiscrizioni generate da click su unsubscribe link nelle email.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `AccountID` | int | ID account |
| `OYBAccountID` | int | On Your Behalf |
| `JobID` | int | Join con `_Job` |
| `ListID` | int | ID lista |
| `BatchID` | int | ID batch |
| `SubscriberID` | int | ID interno |
| `SubscriberKey` | nvarchar | Chiave preferita |
| `EventDate` | datetime | Data/ora disiscrizione (CST) |
| `Domain` | nvarchar | Dominio |
| `IsUnique` | bit | `1` = primo unsubscribe per questo subscriber+job |
| `TriggererSendDefinitionObjectID` | nvarchar | Collega a `_JourneyActivity` |

---

## _Complaint

Segnalazioni spam tramite Feedback Loop (FBL). Solo disponibile se FBL è configurato per il dominio.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `AccountID` | int | ID account |
| `OYBAccountID` | int | On Your Behalf |
| `JobID` | int | Join con `_Job` |
| `SubscriberID` | int | ID interno |
| `SubscriberKey` | nvarchar | Chiave preferita |
| `EventDate` | datetime | Data/ora segnalazione (CST) |
| `IsUnique` | bit | `1` = prima segnalazione |

---

## _JourneyActivity

Attività all'interno di Journey Builder. Collega tracking email a step del journey.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `VersionID` | nvarchar | ID versione del journey |
| `ActivityID` | nvarchar | ID attività nel journey |
| `ActivityName` | nvarchar | Nome dell'attività (es. "Email Benvenuto") |
| `ActivityExternalKey` | nvarchar | External key dell'attività |
| `ActivityType` | nvarchar | Tipo: `EMAILV2`, `WAIT`, `DECISION`... |
| `JourneyActivityObjectID` | nvarchar | **Chiave di join** con `TriggererSendDefinitionObjectID` in `_Sent`, `_Open`, `_Click`, `_Bounce` |

```sql
-- Performance email per step di journey
SELECT
    ja.ActivityName,
    j.EmailName,
    COUNT(DISTINCT s.SubscriberKey) AS Sent,
    COUNT(DISTINCT CASE WHEN o.IsUnique = 1 THEN o.SubscriberKey END) AS UniqueOpens,
    COUNT(DISTINCT CASE WHEN c.IsUnique = 1 THEN c.SubscriberKey END) AS UniqueClicks
FROM [_JourneyActivity] ja
    INNER JOIN [_Sent] s ON s.TriggererSendDefinitionObjectID = ja.JourneyActivityObjectID
    INNER JOIN [_Job] j ON s.JobID = j.JobID
    LEFT JOIN [_Open] o ON s.JobID = o.JobID AND s.SubscriberKey = o.SubscriberKey
    LEFT JOIN [_Click] c ON s.JobID = c.JobID AND s.SubscriberKey = c.SubscriberKey
WHERE s.EventDate >= DATEADD(DAY, -30, GETDATE())
GROUP BY ja.ActivityName, j.EmailName
ORDER BY Sent DESC
```

---

## _Journey

Metadata dei Journey Builder journeys.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `JourneyID` | nvarchar | ID univoco journey |
| `JourneyName` | nvarchar | Nome del journey |
| `VersionID` | nvarchar | ID versione (join con `_JourneyActivity`) |
| `VersionNumber` | int | Numero versione |
| `CreatedDate` | datetime | Data creazione |
| `ModifiedDate` | datetime | Data ultima modifica |
| `JourneyStatus` | nvarchar | `Running`, `Paused`, `Stopped`... |

---

## _Subscribers

Stato dei subscriber nell'account SFMC. Non include attributi custom: solo stato e date.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `SubscriberID` | int | ID interno |
| `SubscriberKey` | nvarchar | Chiave preferita |
| `EmailAddress` | nvarchar | Indirizzo email |
| `Status` | nvarchar | `Active`, `Unsubscribed`, `Bounced`, `Held` |
| `DateHeld` | datetime | Data in cui è stato messo in Held |
| `DateUnsubscribed` | datetime | Data disiscrizione |
| `DateCreated` | datetime | Data creazione subscriber |
| `DateModified` | datetime | Data ultima modifica |
| `PartnerKey` | nvarchar | Chiave partner (se usata) |

---

## _ListSubscribers

Iscrizioni dei subscriber alle liste (non alle DE). Rilevante per account non-enterprise 2.0.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `ListID` | int | ID lista |
| `ListName` | nvarchar | Nome lista |
| `SubscriberID` | int | ID interno |
| `SubscriberKey` | nvarchar | Chiave preferita |
| `Status` | nvarchar | `Active`, `Unsubscribed`... |
| `DateUnsubscribed` | datetime | Data disiscrizione dalla lista |
| `CreatedDate` | datetime | Data iscrizione |

---

## _BusinessUnitUnsubscribes

Disiscrizioni a livello di singola Business Unit (non globale). **Accessibile solo dal Parent BU**.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `BusinessUnitID` | int | ID della BU |
| `SubscriberID` | int | ID interno |
| `SubscriberKey` | nvarchar | Chiave preferita |
| `UnsubDateUTC` | datetime | Data disiscrizione in UTC (attenzione: diverso dalle altre Data Views che usano CST) |
| `UnsubReason` | nvarchar | Motivo disiscrizione |

---

## _EnterpriseAttribute

Attributi di profilo subscriber a livello enterprise. In Enterprise 2.0, contiene le colonne custom aggiunte al profilo.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `SubscriberID` | int | ID interno |
| `SubscriberKey` | nvarchar | Chiave preferita |
| + colonne custom | vari | Una colonna per ogni attributo definito nel profilo enterprise |

---

## Join Patterns

### Pattern 1: Report KPI completo per invio

```sql
-- Full KPI report: Sent, Delivered (stima), Opens, Clicks, Bounces, Unsubs
SELECT
    j.JobID,
    j.EmailName,
    j.EmailSubject,
    j.ActualSchedTime,
    j.SentCount,
    -- Delivered = Sent - Bounced (stima)
    j.SentCount - ISNULL(j.BounceCount, 0)              AS DeliveredEstimate,
    COUNT(DISTINCT CASE WHEN o.IsUnique = 1 THEN o.SubscriberKey END) AS UniqueOpens,
    COUNT(DISTINCT CASE WHEN c.IsUnique = 1 THEN c.SubscriberKey END) AS UniqueClicks,
    COUNT(DISTINCT b.SubscriberKey)                      AS Bounces,
    COUNT(DISTINCT u.SubscriberKey)                      AS Unsubscribes,
    -- Rates
    CAST(COUNT(DISTINCT CASE WHEN o.IsUnique = 1 THEN o.SubscriberKey END) * 100.0
        / NULLIF(j.SentCount - ISNULL(j.BounceCount,0), 0) AS DECIMAL(5,2)) AS OpenRate_Pct,
    CAST(COUNT(DISTINCT CASE WHEN c.IsUnique = 1 THEN c.SubscriberKey END) * 100.0
        / NULLIF(j.SentCount - ISNULL(j.BounceCount,0), 0) AS DECIMAL(5,2)) AS CTR_Pct,
    CAST(COUNT(DISTINCT b.SubscriberKey) * 100.0
        / NULLIF(j.SentCount, 0) AS DECIMAL(5,2))       AS BounceRate_Pct
FROM [_Job] j
    LEFT JOIN [_Open] o         ON j.JobID = o.JobID
    LEFT JOIN [_Click] c        ON j.JobID = c.JobID
    LEFT JOIN [_Bounce] b       ON j.JobID = b.JobID AND b.IsFalseBounce = 0
    LEFT JOIN [_Unsubscribe] u  ON j.JobID = u.JobID AND u.IsUnique = 1
WHERE
    j.ActualSchedTime >= DATEADD(DAY, -30, GETDATE())
    AND j.JobStatus = 'Sent'
GROUP BY
    j.JobID, j.EmailName, j.EmailSubject, j.ActualSchedTime,
    j.SentCount, j.BounceCount
ORDER BY j.ActualSchedTime DESC
```

### Pattern 2: Subscriber-level engagement (per audience building)

```sql
-- Profilo engagement per subscriber (ultimi 90 giorni)
-- Utile per scoring e re-engagement audience
SELECT
    s.SubscriberKey,
    MAX(s.EventDate)    AS LastSentDate,
    COUNT(DISTINCT s.JobID) AS TotalSent,
    COUNT(DISTINCT CASE WHEN o.IsUnique = 1 THEN o.JobID END) AS JobsOpened,
    COUNT(DISTINCT CASE WHEN c.IsUnique = 1 THEN c.JobID END) AS JobsClicked,
    MAX(CASE WHEN o.IsUnique = 1 THEN o.EventDate END) AS LastOpenDate,
    MAX(CASE WHEN c.IsUnique = 1 THEN c.EventDate END) AS LastClickDate
FROM [_Sent] s
    LEFT JOIN [_Open] o     ON s.JobID = o.JobID AND s.SubscriberKey = o.SubscriberKey AND o.IsUnique = 1
    LEFT JOIN [_Click] c    ON s.JobID = c.JobID AND s.SubscriberKey = c.SubscriberKey AND c.IsUnique = 1
WHERE s.EventDate >= DATEADD(DAY, -90, GETDATE())
GROUP BY s.SubscriberKey
```

### Pattern 3: Hard bouncer da escludere

```sql
-- Subscriber con hard bounce negli ultimi 30 giorni da escludere da prossimi invii
SELECT DISTINCT
    b.SubscriberKey,
    b.BounceCategory,
    b.SMTPCode,
    b.EventDate AS BounceDate
FROM [_Bounce] b
WHERE
    b.EventDate >= DATEADD(DAY, -30, GETDATE())
    AND b.BounceType = 'HardBounce'
    AND b.IsFalseBounce = 0
```

### Pattern 4: Subscriber inattivi (re-engagement)

```sql
-- Subscriber che hanno ricevuto almeno 3 email negli ultimi 90 giorni
-- ma non hanno mai aperto
SELECT
    s.SubscriberKey,
    COUNT(DISTINCT s.JobID) AS TotalSent,
    MAX(s.EventDate)        AS LastSentDate
FROM [_Sent] s
    LEFT JOIN [_Open] o ON s.SubscriberKey = o.SubscriberKey
        AND o.EventDate >= DATEADD(DAY, -90, GETDATE())
WHERE
    s.EventDate >= DATEADD(DAY, -90, GETDATE())
    AND o.SubscriberKey IS NULL  -- mai aperto
GROUP BY s.SubscriberKey
HAVING COUNT(DISTINCT s.JobID) >= 3
```
