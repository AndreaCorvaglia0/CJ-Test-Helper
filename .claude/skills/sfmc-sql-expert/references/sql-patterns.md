# SFMC SQL — Pattern Ricorrenti MCC

Libreria di query pronte per i casi d'uso più frequenti del team MCC.
Ogni pattern include commenti operativi e varianti comuni.

---

## Indice

1. [Audience Building](#1-audience-building)
2. [Segmentazione per engagement](#2-segmentazione-per-engagement)
3. [Deduplicazione DE](#3-deduplicazione-de)
4. [Rolling window (finestre temporali)](#4-rolling-window)
5. [Funnel Journey](#5-funnel-journey)
6. [Reporting mensile](#6-reporting-mensile)
7. [Gestione opt-out / soppressione](#7-gestione-opt-out--soppressione)
8. [Audience da DE relazionali](#8-audience-da-de-relazionali)

---

## 1. Audience Building

### Audience base da Master DE con filtro stato

```sql
-- Audience attivi da Master DE, esclusi bounced e unsubscribed
SELECT
    m.SubscriberKey,
    m.EmailAddress,
    m.FirstName,
    m.LastName,
    m.Segment
FROM [MasterDE_Cliente] m
    INNER JOIN [_Subscribers] sub ON m.SubscriberKey = sub.SubscriberKey
WHERE
    sub.Status = 'Active'
    AND m.EmailAddress IS NOT NULL
    AND m.EmailAddress <> ''
    AND m.OptIn = 'Y'
```

### Audience con arricchimento da DE prodotti

```sql
-- Clienti con acquisto negli ultimi 60 giorni + attributi anagrafici
SELECT
    m.SubscriberKey,
    m.EmailAddress,
    m.FirstName,
    p.LastPurchaseDate,
    p.TotalSpend,
    p.ProductCategory
FROM [MasterDE_Cliente] m
    INNER JOIN [DE_Acquisti] p ON m.SubscriberKey = p.SubscriberKey
    INNER JOIN [_Subscribers] sub ON m.SubscriberKey = sub.SubscriberKey
WHERE
    sub.Status = 'Active'
    AND p.LastPurchaseDate >= DATEADD(DAY, -60, GETDATE())
```

---

## 2. Segmentazione per Engagement

### Segmenti RFM semplificati (Recency / Frequency basata su email)

```sql
-- Classificazione engagement in 4 fasce basata su aperture ultimi 90 giorni
SELECT
    eng.SubscriberKey,
    eng.TotalSent,
    eng.JobsOpened,
    eng.DaysSinceLastOpen,
    CASE
        WHEN eng.DaysSinceLastOpen <= 30 AND eng.JobsOpened >= 3 THEN 'Attivo_Alto'
        WHEN eng.DaysSinceLastOpen <= 60 AND eng.JobsOpened >= 1 THEN 'Attivo_Medio'
        WHEN eng.DaysSinceLastOpen <= 90                          THEN 'Dormiente'
        ELSE 'Inattivo'
    END AS EngagementSegment
FROM (
    SELECT
        s.SubscriberKey,
        COUNT(DISTINCT s.JobID)                                         AS TotalSent,
        COUNT(DISTINCT CASE WHEN o.IsUnique = 1 THEN o.JobID END)       AS JobsOpened,
        DATEDIFF(DAY,
            MAX(CASE WHEN o.IsUnique = 1 THEN o.EventDate END),
            GETDATE()
        )                                                               AS DaysSinceLastOpen
    FROM [_Sent] s
        LEFT JOIN [_Open] o ON s.JobID = o.JobID
            AND s.SubscriberKey = o.SubscriberKey AND o.IsUnique = 1
    WHERE s.EventDate >= DATEADD(DAY, -90, GETDATE())
    GROUP BY s.SubscriberKey
) eng
```

---

## 3. Deduplicazione DE

### Deduplica per SubscriberKey (tieni l'ultimo record)

```sql
-- Mantieni solo il record più recente per ogni SubscriberKey
SELECT
    SubscriberKey,
    EmailAddress,
    FirstName,
    LastName,
    UpdatedAt
FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY SubscriberKey
            ORDER BY UpdatedAt DESC
        ) AS rn
    FROM [DE_Contatti_Raw]
) dedup
WHERE rn = 1
```

### Deduplica per email (case-insensitive)

```sql
SELECT
    SubscriberKey,
    EmailAddress,
    FirstName
FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY LOWER(EmailAddress)
            ORDER BY CreatedDate DESC
        ) AS rn
    FROM [DE_Import]
    WHERE EmailAddress IS NOT NULL AND EmailAddress <> ''
) dedup
WHERE rn = 1
```

---

## 4. Rolling Window

### Ultimi N giorni (parametrizzato per Automation Studio)

```sql
-- Attività degli ultimi 7 / 30 / 90 giorni
-- Cambia il valore -7 / -30 / -90 secondo il periodo desiderato

SELECT
    s.SubscriberKey,
    s.JobID,
    s.EventDate
FROM [_Sent] s
WHERE s.EventDate >= DATEADD(DAY, -30, GETDATE())
```

### Mese corrente vs mese precedente

```sql
SELECT
    CASE
        WHEN j.ActualSchedTime >= DATEADD(MONTH, DATEDIFF(MONTH, 0, GETDATE()), 0)
        THEN 'Mese_Corrente'
        ELSE 'Mese_Precedente'
    END AS Periodo,
    COUNT(DISTINCT j.JobID) AS NumInvii,
    SUM(j.SentCount)        AS TotaleSent
FROM [_Job] j
WHERE
    j.ActualSchedTime >= DATEADD(MONTH, -1,
        DATEADD(MONTH, DATEDIFF(MONTH, 0, GETDATE()), 0)
    )
    AND j.JobStatus = 'Sent'
GROUP BY
    CASE
        WHEN j.ActualSchedTime >= DATEADD(MONTH, DATEDIFF(MONTH, 0, GETDATE()), 0)
        THEN 'Mese_Corrente'
        ELSE 'Mese_Precedente'
    END
```

---

## 5. Funnel Journey

### Conteggio contatti per step di journey

```sql
-- Quanti contatti hanno completato ogni step di un journey specifico
SELECT
    ja.ActivityName,
    ja.ActivityType,
    COUNT(DISTINCT s.SubscriberKey) AS ContactsReached
FROM [_JourneyActivity] ja
    INNER JOIN [_Sent] s
        ON s.TriggererSendDefinitionObjectID = ja.JourneyActivityObjectID
    INNER JOIN [_Journey] jrn
        ON ja.VersionID = jrn.VersionID
WHERE
    jrn.JourneyName = 'NOME_JOURNEY'   -- sostituire con nome reale
    AND s.EventDate >= DATEADD(DAY, -90, GETDATE())
GROUP BY ja.ActivityName, ja.ActivityType
ORDER BY ContactsReached DESC
```

### Tasso di conversione tra step

```sql
-- Confronto tra step 1 (es. email benvenuto) e step 2 (es. email offerta)
-- Utile per identificare drop-off nel journey
SELECT
    step1.ContactsAtStep1,
    step2.ContactsAtStep2,
    CAST(step2.ContactsAtStep2 * 100.0
        / NULLIF(step1.ContactsAtStep1, 0) AS DECIMAL(5,2)) AS ConversionRate_Pct
FROM (
    SELECT COUNT(DISTINCT s.SubscriberKey) AS ContactsAtStep1
    FROM [_Sent] s
    INNER JOIN [_JourneyActivity] ja ON s.TriggererSendDefinitionObjectID = ja.JourneyActivityObjectID
    WHERE ja.ActivityName = 'Email_Step1_Benvenuto'
        AND s.EventDate >= DATEADD(DAY, -90, GETDATE())
) step1
CROSS JOIN (
    SELECT COUNT(DISTINCT s.SubscriberKey) AS ContactsAtStep2
    FROM [_Sent] s
    INNER JOIN [_JourneyActivity] ja ON s.TriggererSendDefinitionObjectID = ja.JourneyActivityObjectID
    WHERE ja.ActivityName = 'Email_Step2_Offerta'
        AND s.EventDate >= DATEADD(DAY, -90, GETDATE())
) step2
```

---

## 6. Reporting Mensile

### Riepilogo mensile per nome campagna (etichetta in EmailName)

```sql
-- Aggregato mensile: invii, open, click per campagna
SELECT
    FORMAT(j.ActualSchedTime, 'yyyy-MM')    AS Mese,
    j.EmailName,
    COUNT(DISTINCT j.JobID)                 AS NumInvii,
    SUM(j.SentCount)                        AS TotalSent,
    COUNT(DISTINCT CASE WHEN o.IsUnique = 1 THEN o.SubscriberKey + CAST(o.JobID AS NVARCHAR) END) AS UniqueOpens,
    COUNT(DISTINCT CASE WHEN c.IsUnique = 1 THEN c.SubscriberKey + CAST(c.JobID AS NVARCHAR) END) AS UniqueClicks
FROM [_Job] j
    LEFT JOIN [_Open] o     ON j.JobID = o.JobID
    LEFT JOIN [_Click] c    ON j.JobID = c.JobID
WHERE
    j.ActualSchedTime >= DATEADD(MONTH, -6, GETDATE())
    AND j.JobStatus = 'Sent'
GROUP BY
    FORMAT(j.ActualSchedTime, 'yyyy-MM'),
    j.EmailName
ORDER BY Mese DESC, TotalSent DESC
```

---

## 7. Gestione Opt-out / Soppressione

### Lista soppressione globale (unsubscribed + bounced + held)

```sql
-- DE di soppressione da usare come esclusione in send definition
SELECT DISTINCT
    sub.SubscriberKey,
    sub.EmailAddress,
    sub.Status,
    CASE
        WHEN sub.Status = 'Unsubscribed' THEN 'Unsubscribed'
        WHEN sub.Status = 'Bounced'      THEN 'HardBounce'
        WHEN sub.Status = 'Held'         THEN 'Held'
    END AS SuppressionReason
FROM [_Subscribers] sub
WHERE sub.Status IN ('Unsubscribed', 'Bounced', 'Held')
```

### Nuovi opt-out delle ultime 24 ore (per sincronizzazione CRM)

```sql
-- Utile per automation di sincronizzazione giornaliera verso CRM
SELECT
    u.SubscriberKey,
    u.EventDate AS UnsubscribeDate,
    j.EmailName AS UnsubscribedFrom
FROM [_Unsubscribe] u
    LEFT JOIN [_Job] j ON u.JobID = j.JobID
WHERE
    u.EventDate >= DATEADD(HOUR, -24, GETDATE())
    AND u.IsUnique = 1
ORDER BY u.EventDate DESC
```

---

## 8. Audience da DE Relazionali

### JOIN tra più DE con logica AND/OR

```sql
-- Clienti: segmento "Premium" E (prodotto X O prodotto Y) E NON già contattati
SELECT DISTINCT
    m.SubscriberKey,
    m.EmailAddress,
    m.FirstName,
    m.Segment
FROM [MasterDE] m
    -- Condizione 1: Premium
    INNER JOIN [DE_Segmenti] seg
        ON m.SubscriberKey = seg.SubscriberKey
        AND seg.SegmentName = 'Premium'
    -- Condizione 2: ha acquistato prodotto X o Y
    INNER JOIN [DE_Acquisti] acq
        ON m.SubscriberKey = acq.SubscriberKey
        AND acq.ProductCode IN ('PROD_X', 'PROD_Y')
    -- Esclusione: non già inviati in questa campagna
    LEFT JOIN [DE_GiaContattati_CampagnaXYZ] cont
        ON m.SubscriberKey = cont.SubscriberKey
    INNER JOIN [_Subscribers] sub ON m.SubscriberKey = sub.SubscriberKey
WHERE
    sub.Status = 'Active'
    AND cont.SubscriberKey IS NULL  -- escludi già contattati
```

### NOT EXISTS per esclusione performante (alternativa a LEFT JOIN + IS NULL)

```sql
-- Più performante su DE grandi rispetto a LEFT JOIN + IS NULL
SELECT
    m.SubscriberKey,
    m.EmailAddress
FROM [MasterDE] m
WHERE
    m.OptIn = 'Y'
    AND NOT EXISTS (
        SELECT 1
        FROM [DE_Soppressione] sup
        WHERE sup.SubscriberKey = m.SubscriberKey
    )
```
