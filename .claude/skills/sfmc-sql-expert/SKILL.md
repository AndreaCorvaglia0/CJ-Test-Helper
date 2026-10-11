---
name: sfmc-sql-expert
description: >
  Genera, ottimizza e spiega query SQL per Salesforce Marketing Cloud (SFMC/MCE).
  Attiva questa skill SEMPRE quando l'utente menziona: SQL, query, Data Extension, DE,
  Data View, _Sent, _Open, _Click, _Bounce, _Job, _JourneyActivity, Automation Studio,
  Query Activity, segmentazione, audience, join, lookup, ENT., SubscriberKey, JobID,
  IsUnique, timeout, DATEADD, o qualsiasi richiesta di estrarre/trasformare dati in SFMC.
  Usala anche per ottimizzare query lente, fare troubleshooting su risultati inattesi,
  costruire reporting DE, o spiegare come funziona il database di SFMC.
  Quando in dubbio, attivala: meglio usarla in eccesso che produrre SQL generico.
---

# SFMC SQL Expert

Skill per generare query SQL corrette, ottimizzate e pronte all'uso per l'ambiente
Salesforce Marketing Cloud Engagement (MCE), calibrata sul contesto MCC Lutech.

---

## Regole fondamentali dell'SQL in SFMC

1. **Timeout 30 minuti**: ogni Query Activity che supera i 30' viene terminata. Ottimizzare è obbligatorio, non opzionale.
2. **Database relazionale proprietario**: SFMC usa T-SQL (SQL Server dialect). Alcune funzioni standard non sono disponibili (es. `TOP` sì, `LIMIT` no).
3. **Data Views sono read-only**: non si può fare `INSERT/UPDATE` su `_Sent`, `_Open` etc. Si scrive sempre su una Data Extension target.
4. **Naming con ENT.**: per referenziare DE condivise a livello enterprise in ambienti multi-BU usare il prefisso `ENT.` → `[ENT.NomeDE]`.
5. **IsUnique per deduplicazione**: nei tracking Data Views `_Open` e `_Click`, `IsUnique = 1` indica il primo evento per quel subscriber+job. Usarlo per conteggi accurati.
6. **Date in CST**: tutti i timestamp nelle Data Views sono in Central Standard Time (CST). Daylight Saving Time non viene osservato.
7. **NULL handling**: usare `ISNULL(campo, valore_default)` o `COALESCE`. I join su campi NULL producono righe inattese.
8. **SubscriberKey vs SubscriberID**: preferire sempre `SubscriberKey` (stringa alfanumerica) come chiave di join. `SubscriberID` è un intero interno che può variare tra BU.

---

## Struttura delle query: template base

```sql
-- ============================================================
-- NOME QUERY: [NomeQuery_MCC_Cliente]
-- SCOPO: [Descrizione breve]
-- TARGET DE: [NomeDE_Target]
-- OVERWRITE / APPEND: [Overwrite | Append]
-- AUTORE: MCC Lutech | DATA: YYYY-MM-DD
-- NOTE: [Eventuali dipendenze o condizioni]
-- ============================================================

SELECT
    campo1,
    campo2,
    ISNULL(campo3, 'default') AS campo3_clean
FROM [NomeDEsorgente] s
    INNER JOIN [AltreDE] a ON s.SubscriberKey = a.SubscriberKey
WHERE
    s.campo = 'valore'
    AND s.DataCampo >= DATEADD(DAY, -30, GETDATE())
```

---

## Riferimenti tecnici: leggi i file in `references/`

Quando la richiesta coinvolge un'area specifica, leggi il file corrispondente prima di rispondere:

| File | Quando leggerlo |
|------|----------------|
| `references/data-views.md` | Query su _Sent, _Open, _Click, _Bounce, _Unsubscribe, _Job, _JourneyActivity e altre system tables |
| `references/sql-patterns.md` | Pattern ricorrenti: audience building, engagement scoring, deduplicazione, rolling window, funnel |
| `references/best-practices.md` | Ottimizzazione performance, troubleshooting, naming convention MCC |

---

## Flusso di risposta

1. **Identifica il contesto**: DE sorgente, target, obiettivo della query, BU singola o enterprise
2. **Leggi il reference file** pertinente (vedi tabella sopra)
3. **Genera la query** con header commentato, colonne esplicite, alias chiari
4. **Aggiungi note operative**: overwrite vs append, scheduling consigliato in Automation Studio, rischi noti
5. **Se la query è complessa**: spiega brevemente la logica (utile per il team che la manuterrà)

---

## Contesto MCC Lutech

- I clienti enterprise usano tipicamente ambienti **multi-BU** → attenzione al prefisso `ENT.`
- Il team usa **Automation Studio** come scheduler principale
- Le DE di reporting vengono spesso alimentate via Query Activity e poi lette da **Tableau** o **CRM Analytics**
- Il naming convention tipico del MCC: `[Cliente]_[Tipo]_[Descrizione]` (es. `ENEL_RPT_EngagementMensile`)
- Audience size clienti: generalmente > 100.000 contatti → performance è critica
