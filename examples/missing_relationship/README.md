# missing_relationship

Un attribute set letto da uno split, ma senza nessuna relazione nell'export: `attributeRelationships` è vuoto,
il `leftRelationships` dell'attribute set e il `groupToSetRelationshipId` della condizione nominano un id che non
esiste. Package Manager lo segnala nelle `issues` del journey ("Unable to find attribute relationship"), come
nell'export reale da cui è presa la forma.

## Journey

```
SPLIT-1 "Channel"        Event.Channel Equal 'Email'      -> SPLIT-2
                         remainder                        -> UPDATE-3 "Other channel"
SPLIT-2 "Do not track"   DE_MR_Consent.DoNotTrack Is false -> UPDATE-1 "Tracked email"
                         remainder                        -> UPDATE-2 "Untracked email"
```

Tabelle: `DE_MR_Entry` (ingresso da Run Once: `SubscriberKey`, `EmailAddress`, `Channel`), `DE_MR_Consent`
(`SubscriberKey` chiave primaria, `DoNotTrack` Boolean; attribute set senza relazione), `DE_MR_Log` (solo
scritta).

Issues nell'export:

- sul journey, livello `WARNING`: `ENTITY_NOT_FOUND` di `attributeRelationships`, causa di livello `ERROR`
  "Unable to find attribute relationship", attività "Do not track";
- sulla data extension `DE_MR_Entry`, livello `INFO`: `UNSUPPORTED_AMPSCRIPT` / `UNRESOLVED_VARIABLE`.

## Risposta attesa, passo per passo

1. **SPLIT-2 non supportato, con il motivo.** Spec, "Data sources of a condition": "Missing relationship. An
   attribute set read by a split with no relationship in the export: its conditions are unsupported, with the
   reason 'relationship missing in the export'." `path_a` è **non coperto** e il motivo nomina la relazione
   mancante; il remainder, che dipende dalla stessa condizione, è **non coperto**, con un motivo che parla di
   elemento non supportato o della relazione mancante.
2. **SPLIT-1 supportato** (Journey Data sulla tabella di ingresso): `Email` -> SPLIT-2, altrimenti UPDATE-3.
   Entrambi **coperti**.
3. **Casi: 1 scenario, 2 casi, 6 contatti.** `Channel` = `Email` (il percorso si ferma a SPLIT-2) e `Channel`
   non vuoto diverso da `Email` (UPDATE-3, preferenza "not null"). Nessun branch dipende da `DoNotTrack`, quindi
   un solo scenario basta per tutti e due i casi.
4. **Issues nel report.** "Package Manager `issues` of level warning or error are listed in the report." Il report
   nomina Package Manager e riporta l'issue del journey (`ENTITY_NOT_FOUND` o il suo messaggio). L'issue `INFO`
   resta fuori: il report non contiene `UNSUPPORTED_AMPSCRIPT` né `UNRESOLVED_VARIABLE`.

## Non verificato

- Se `DE_MR_Consent` riceve un CSV e a quale livello. La regola di selezione darebbe un CSV ("Any table named in a
  split condition"), ma senza relazione il livello non si ricava dal campo di join e la spec non dice cosa fare:
  `csv_tables` e il livello di questa tabella non sono controllati.
- Il testo esatto del motivo: si controlla solo la parola "relazione" (glossario: relationship -> relazione).
