# Package export format (what the loader reads)

Observed on the pilot export (`fixtures/CJ template complesso-v1.json`, Package Manager `modelVersion` 9).
Only the parts the generator uses are described. Hand-made examples must follow this shape.

```json
{
  "name": "CJ template complesso",
  "selectedEntities": { "journeys": ["<journey id>"] },
  "entities": {
    "journeys":               { "<id>": { "data": { ...journey... } } },
    "eventDefinitions":       { "<id>": { "data": { ...event... } } },
    "dataExtensions":         { "<id>": { "data": { ...table... } } },
    "attributeSets":          { "<id>": { "data": { ...set... } } },
    "attributeRelationships": { "<id>": { "data": { ...relationship... } } },
    "attributeGroups":        { "<id>": { "data": { "name": "DEMO_SkyDE" } } },
    "automations":            { "<id>": { "data": { ...automation... } } },
    "queryActivities":        { "<id>": { "data": { ...query... } } },
    "assets":                 { "<id>": { "data": { ...email... } } }
  }
}
```

Every entity is `{"issues": [], "originID": ..., "originEID": ..., "data": {...}}`; only `data` matters.

## References

Cross references are strings `{{mcpm#/entities/<kind>/<id>/data/<path>}}`, resolved to the value found at
`<path>` inside that entity's `data`. Seen paths: `name`, `id`, `eventDefinitionKey`, `namePrefix`,
`fields/name:<FieldName>/id`, `data/email/legacy/legacyId`. The export does not carry real ids, so `.../id`
resolves to the entity id (the key in the `entities` map) and `fields/name:X/id` resolves to the field name `X`.
Other placeholders (`{{mcpm:senderProfile}}`, `{{Context.*}}`, `{{Contact.*}}`, `{{Event.*}}`) are not entity references.

## Data extension

```json
{ "name": "DE_NCRM_AD_HOC_CONFIG", "customerKey": "DEFDFCEA-...", "isSendable": false,
  "sendableCustomObjectField": null, "sendableSubscriberField": null,
  "fields": [
    { "name": "CampaignName", "type": "Text", "length": 250, "isPrimaryKey": true, "isNullable": false,
      "ordinal": 0, "defaultValue": null },
    { "name": "ACTIVE", "type": "Boolean", "length": null, "isPrimaryKey": false, "isNullable": false,
      "ordinal": 15, "defaultValue": "False" } ] }
```

Types seen: `Text`, `Boolean`, `Date`, `EmailAddress`, `Phone`. `defaultValue` is absent or a string
(`"False"`, `"false"`, `"GETDATE()"`, `"GetDate()"`). Sendable tables carry `"sendableCustomObjectField": "ContactId"`
and `"sendableSubscriberField": "_SubscriberKey"`: that field is the contact key.

## Attribute set and relationships (Contact Builder model)

An attribute set names a table:

```json
{ "name": "DE_NCRM_AD_HOC_CONFIG", "storageLogicalType": "DataExtension", "isRoot": false,
  "storageName": "{{mcpm#/entities/dataExtensions/<de id>/data/name}}",
  "groupId": "{{mcpm#/entities/attributeGroups/<group id>/data/id}}", "leftRelationships": [...] }
```

A relationship links two sets on one field pair (`leftAttributeName` is missing on group-to-set links):

```json
{ "name": "DE_NCM_AdHoc_Entry -> DE_NCRM_AD_HOC_CONFIG",
  "isGroupToSetRelationship": false,
  "relationshipAttributes": [ { "leftAttributeName": "CampaignName", "rightAttributeName": "CampaignName",
       "rightDataExtensionID": "{{mcpm#/entities/dataExtensions/<de id>/data/id}}",
       "rightAttributeID": "{{mcpm#/entities/dataExtensions/<de id>/data/fields/name:CampaignName/id}}" } ],
  "leftItem":  { "relationshipType": "AttributeSet", "cardinality": "One",
                 "identifier": "{{mcpm#/entities/attributeSets/<set id>/data/id}}" },
  "rightItem": { "relationshipType": "AttributeSet", "cardinality": "One",
                 "name": "{{mcpm#/entities/attributeSets/<set id>/data/name}}" } }
```

Pilot links: group `DEMO_SkyDE` -> `SF_Master_DataExtension_DE` on `ContactId` (group-to-set);
`SF_Master_DataExtension_DE.ContactId` -> `DE_NCM_AdHoc_Entry.ContactId`; `DE_NCM_AdHoc_Entry.CampaignName` -> `DE_NCRM_AD_HOC_CONFIG.CampaignName`.

## Event definition (entry source)

```json
{ "name": "CJ_SkYDE_NCRM_Demo_final", "type": "AutomationAudience",
  "eventDefinitionKey": "DEAudience-77cdeeda-...",
  "dataExtensionId": "{{mcpm#/entities/dataExtensions/<entry de id>/data/id}}",
  "arguments": { "automationId": "{{mcpm#/entities/automations/<automation id>/data/id}}", "criteria": "" } }
```

## Automation and queries

```json
{ "name": "A_SkyDE_NCRM_AdHoc_CJ_entry",
  "steps": [ { "activities": [ { "name": "{{mcpm#/entities/queryActivities/<q id>/data/name}}",
                                  "activityObjectId": "{{mcpm#/entities/queryActivities/<q id>/data/id}}",
                                  "objectTypeId": 300 } ] } ] }
```

`objectTypeId` 300 = query activity, 1000 = data verification. A query:

```json
{ "name": "Q_SKYDE_AdHoc_Target", "targetUpdateTypeName": "Update",
  "targetId": "{{mcpm#/entities/dataExtensions/<entry de id>/data/id}}",
  "queryText": "SELECT M.ContactId, ... FROM {{mcpm#/entities/dataExtensions/<m>/data/namePrefix}}[{{mcpm#/entities/dataExtensions/<m>/data/name}}] M JOIN ... WHERE C.active = 'True' AND ..." }
```

## Email asset

```json
{ "name": "Demo Sky", "assetType": { "name": "htmlemail" },
  "data": { "email": { "legacy": { "legacyId": 1806207 } } },
  "views": { "subjectline": { "content": "DEMO SKY" }, "html": { "content": "<!DOCTYPE html>..." }, "text": { "content": "" } } }
```

(The pilot's asset has no `legacy` block; the email activity's `emailId` reference still names the asset id.)

## Journey

```json
{ "name": "CJ_SkYDE_NCRM_Demo_final", "key": "255ab106-...", "definitionType": "Multistep",
  "triggers": [ { "key": "TRIGGER", "type": "AutomationAudience",
                  "metaData": { "eventDefinitionId": "{{mcpm#/entities/eventDefinitions/<ev id>/data/id}}",
                                "eventDefinitionKey": "{{mcpm#/entities/eventDefinitions/<ev id>/data/eventDefinitionKey}}" } } ],
  "defaults": { "email": [ "{{Event.{{mcpm#/entities/eventDefinitions/<ev id>/data/eventDefinitionKey}}.\"Emailaddress\"}}" ] },
  "activities": [ ... ] }
```

Every activity has `key`, `type`, `name`, `outcomes: [ { "key", "next", "arguments", "metaData": { "label" } } ]`.
An outcome without `next` is a journey exit. The start activity is the one no `next` points to.

### Decision split `MULTICRITERIADECISION`

```json
{ "key": "MULTICRITERIADECISIONV2-2", "type": "MULTICRITERIADECISION", "name": "Channel1",
  "configurationArguments": { "criteria": {
     "default_path_1": "<FilterDefinition><ConditionSet Operator=\"AND\" ConditionSetName=\"Individual Filter Grouping\"><Condition Key=\"{{mcpm#/entities/attributeSets/<set id>/data/name}}.CHANNEL1\" Operator=\"Equal\"><AttributePath RelationshipID=\"...\"><Value><![CDATA[Email]]></Value></AttributePath></Condition></ConditionSet></FilterDefinition>",
     "c8b5ecdc-...": "<FilterDefinition>...</FilterDefinition>" } },
  "outcomes": [
    { "key": "default_path_1", "next": "MULTICRITERIADECISIONV2-3", "metaData": { "label": "Email", "criteriaDescription": "CHANNEL1 equal Email" } },
    { "key": "c8b5ecdc-...",   "next": "MULTICRITERIADECISIONV2-7", "metaData": { "label": "DM" } },
    { "key": "remainder_path", "next": null, "metaData": { "label": "Remainder" } } ] }
```

Outcomes are evaluated in order; `remainder_path` has no criteria. Nested groups:
`<ConditionSet Operator="AND"><Condition .../><ConditionSet Operator="OR"><Condition .../><Condition Operator="IsNull"><Value><![CDATA[]]></Value></Condition></ConditionSet></ConditionSet>`.
Condition `Key` is `<attribute set name>.<field name>`; field names may contain spaces (`Control Group Required`).
Boolean values are written `true` / `false`. Operators seen: `Is`, `Equal`, `IsNull`.

### Engagement split `ENGAGEMENTDECISION`

```json
{ "key": "ENGAGEMENTSPLITV2-1", "type": "ENGAGEMENTDECISION", "name": "Open Demo Sky",
  "metaData": { "refActivityName": "Demo Sky" },
  "configurationArguments": { "statsTypeId": 2, "refActivityCustomerKey": "EMAILV2-1", "engagementUrls": { "urls": [] } },
  "outcomes": [ { "key": "branchResult-1", "arguments": { "when": true },  "metaData": { "label": "Yes" }, "next": "..." },
                { "key": "branchResult-2", "arguments": { "when": false }, "metaData": { "label": "No" },  "next": "..." } ] }
```

`statsTypeId` 2 = open, 3 = click (as named in the pilot). `refActivityCustomerKey` is the key of the email activity.

### Random split `RANDOMSPLIT`

```json
{ "key": "RANDOMSPLITV2-1", "type": "RANDOMSPLIT", "name": "",
  "outcomes": [ { "key": "branchResult-1", "arguments": { "percentage": 90 }, "metaData": { "label": "90%" }, "next": "..." },
                { "key": "branchResult-2", "arguments": { "percentage": 10 }, "metaData": { "label": "10%" }, "next": "..." } ] }
```

### Waits

Wait by duration: `{"type": "WAIT", "metaData": {"uiType": "WAITBYDURATION"}, "configurationArguments": {"waitDuration": 1, "waitUnit": "MINUTES", "timeZone": "W. Europe Standard Time"}}`.

Wait by attribute: `{"type": "WAIT", "metaData": {"uiType": "WAITBYATTRIBUTE", "attribute": {"id": "{{mcpm#/entities/attributeSets/<set id>/data/name}}.WAIT1", "displayType": "Date"}}, "configurationArguments": {"waitEndDateAttributeExpression": "{{Contact.Attribute.Contacts.SF_Master_DataExtension_DE.DE_NCM_AdHoc_Entry.DE_NCRM_AD_HOC_CONFIG.\"WAIT1\"}}", "timeZone": "W. Europe Standard Time"}}`.

Send-time wait: `{"type": "STOWAIT", "configurationArguments": {"params": {"slidingWindowHours": 24}}}`.

### Email `EMAILV2`

```json
{ "key": "EMAILV2-1", "type": "EMAILV2", "name": "Demo Sky",
  "configurationArguments": { "triggeredSend": { "emailId": "{{mcpm#/entities/assets/1806207/data/data/email/legacy/legacyId}}", "emailSubject": "DEMO SKY" } },
  "outcomes": [ { "key": "...", "next": "WAITBYATTRIBUTE-1" } ] }
```

### Update contact `UPDATECONTACTDATA`

```json
{ "key": "UPDATECONTACTDATAV2-2", "type": "UPDATECONTACTDATA", "name": "DM",
  "arguments": { "activityData": { "updateContactFields": [
     { "dataExtensionId": "{{mcpm#/entities/dataExtensions/<de id>/data/id}}",
       "field": "{{mcpm#/entities/dataExtensions/<de id>/data/fields/name:CampaignName/id}}", "value": "DemoSKY" },
     { "dataExtensionId": "...", "field": ".../fields/name:Mailing_Timestamp/id}}", "value": "{{DateTime.Now}}" } ] } } }
```

Values may be strings or numbers (`"value": 1`).
