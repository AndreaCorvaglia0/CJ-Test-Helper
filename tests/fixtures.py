"""A small synthetic Package Manager export exercising every feature the engine handles.

Journey:
  D0  Config.CG is true        -> RS (random 90/10: D1 | U0)   else -> D1
  D1  Config.CHANNEL = Email   -> E1                            else -> U1 (end)
  E1  email                    -> W1 (wait until Config.WAIT1)  -> G1
  G1  opened E1?  yes -> U2 (end)   no -> D2
  D2  Master.Consent is true AND (Master.Dunning is false OR null) -> U3 (end)   else -> end
"""
import json
from pathlib import Path

MASTER, ENTRY, CONFIG, TARGET = "de-master", "de-entry", "de-config", "de-target"
S_MASTER, S_ENTRY, S_CONFIG = "set-master", "set-entry", "set-config"
R_ROOT, R_ME, R_EC = "rel-root", "rel-me", "rel-ec"


def ref(kind, eid, prop):
    return "{{mcpm#/entities/%s/%s/data/%s}}" % (kind, eid, prop)


def field(name, type_="Text", pk=False, nullable=True, length=50, default=None):
    return {"name": name, "type": type_, "length": length, "isPrimaryKey": pk, "isNullable": nullable,
            "defaultValue": default}


def de(name, fields):
    return {"data": {"name": name, "customerKey": name.upper(), "fields": fields, "isSendable": True}}


def cond(set_id, fname, op, value=""):
    return (f'<Condition Key="{ref("attributeSets", set_id, "name")}.{fname}" Operator="{op}">'
            f'<Value><![CDATA[{value}]]></Value></Condition>')


def criteria(*conds, op="AND"):
    return f'<FilterDefinition><ConditionSet Operator="{op}" ConditionSetName="g">{"".join(conds)}</ConditionSet></FilterDefinition>'


def act(key, type_, outcomes, name="", config=None, arguments=None):
    return {"key": key, "type": type_, "name": name or key, "outcomes": outcomes,
            "configurationArguments": config or {}, "arguments": arguments or {}}


def out(key, next_=None, label=None, **args):
    o = {"key": key, "metaData": {"label": label or key}, "arguments": args}
    if next_:
        o["next"] = next_
    return o


def update(key, value):
    return act(key, "UPDATECONTACTDATA", [out(key + "-o")], name=key, arguments={"activityData": {"updateContactFields": [
        {"dataExtensionId": ref("dataExtensions", MASTER, "id"),
         "field": ref("dataExtensions", MASTER, "fields/name:Note/id"), "value": value}]}})


def package() -> dict:
    dunning_or_null = (f'<ConditionSet Operator="OR" ConditionSetName="g">{cond(S_MASTER, "Dunning", "Is", "false")}'
                       f'{cond(S_MASTER, "Dunning", "IsNull")}</ConditionSet>')
    activities = [
        act("D0", "MULTICRITERIADECISION", [out("cg", "RS", "true"), out("remainder_path", "D1", "false")],
            name="CG required", config={"criteria": {"cg": criteria(cond(S_CONFIG, "CG", "Is", "true"))}}),
        act("RS", "RANDOMSPLIT", [out("b1", "D1", "90%", percentage=90), out("b2", "U0", "10%", percentage=10)]),
        update("U0", "control"),
        act("D1", "MULTICRITERIADECISION", [out("email", "E1", "Email"), out("remainder_path", "U1", "Remainder")],
            name="Channel", config={"criteria": {"email": criteria(cond(S_CONFIG, "CHANNEL", "Equal", "Email"))}}),
        update("U1", "other channel"),
        act("E1", "EMAILV2", [out("e1-o", "W1")], name="Welcome"),
        act("W1", "WAIT", [out("w1-o", "G1")], name="on WAIT1", config={
            "waitEndDateAttributeExpression": '{{Contact.Attribute.Contacts.Master.Entry.Config."WAIT1"}}'}),
        act("G1", "ENGAGEMENTDECISION", [out("yes", "U2", "Yes", when=True), out("no", "D2", "No", when=False)],
            name="Open Welcome", config={"refActivityCustomerKey": "E1"}),
        update("U2", "opened"),
        act("D2", "MULTICRITERIADECISION", [out("ok", "U3", "true"), out("remainder_path", None, "false")],
            name="Consent", config={"criteria": {"ok": criteria(cond(S_MASTER, "Consent", "Is", "true"), dunning_or_null)}}),
        update("U3", "consented"),
    ]
    sql = (f"SELECT M.ContactId, C.CampaignName FROM {ref('dataExtensions', MASTER, 'namePrefix')}"
           f"[{ref('dataExtensions', MASTER, 'name')}] M "
           f"JOIN [{ref('dataExtensions', TARGET, 'name')}] T ON M.ContactId = T.SalesforceId "
           f"JOIN [{ref('dataExtensions', CONFIG, 'name')}] C ON T.Description = C.CampaignName "
           f"/* LEFT JOIN [Nope] N ON 1=1 */ WHERE C.ACTIVE = 'True' "
           f"AND CAST(GETUTCDATE() AS DATE) >= CAST(START_DATE AS DATE)")
    return {
        "entities": {
            "dataExtensions": {
                MASTER: de("Master", [field("ContactId", pk=True, nullable=False), field("Email", "EmailAddress", length=254),
                                      field("Consent", "Boolean"), field("Dunning", "Boolean"), field("Note")]),
                ENTRY: de("Entry", [field("ContactId", pk=True, nullable=False), field("CampaignName", pk=True, nullable=False),
                                    field("Email", "EmailAddress", length=254)]),
                CONFIG: de("Config", [field("CampaignName", pk=True, nullable=False), field("CHANNEL", nullable=False),
                                      field("CG", "Boolean", nullable=False, default="False"),
                                      field("ACTIVE", "Boolean", nullable=False), field("START_DATE", "Date", nullable=False),
                                      field("WAIT1", "Date", nullable=False)]),
                TARGET: de("Target", [field("SalesforceId", pk=True, nullable=False),
                                      field("Description", pk=True, nullable=False, length=255)]),
            },
            "attributeGroups": {"grp": {"data": {"name": "Demo"}}},
            "attributeSets": {
                s: {"data": {"name": n, "storageReferenceID": {"type": "guid", "value": ref("dataExtensions", d, "id")}}}
                for s, n, d in ((S_MASTER, "Master", MASTER), (S_ENTRY, "Entry", ENTRY), (S_CONFIG, "Config", CONFIG))},
            "attributeRelationships": {
                R_ROOT: {"data": {"name": "root", "leftItem": {"relationshipType": "AttributeGroup", "cardinality": "One"},
                                  "rightItem": {"relationshipType": "AttributeSet", "cardinality": "One",
                                                "name": ref("attributeSets", S_MASTER, "name")},
                                  "relationshipAttributes": [{"rightAttributeName": "ContactId"}]}},
                R_ME: {"data": {"name": "m-e", "leftItem": {"relationshipType": "AttributeSet", "cardinality": "One",
                                                            "identifier": ref("attributeSets", S_MASTER, "id")},
                                "rightItem": {"relationshipType": "AttributeSet", "cardinality": "Many",
                                              "name": ref("attributeSets", S_ENTRY, "name")},
                                "relationshipAttributes": [{"leftAttributeName": "ContactId", "rightAttributeName": "ContactId"}]}},
                R_EC: {"data": {"name": "e-c", "leftItem": {"relationshipType": "AttributeSet", "cardinality": "Many",
                                                            "identifier": ref("attributeSets", S_ENTRY, "id")},
                                "rightItem": {"relationshipType": "AttributeSet", "cardinality": "One",
                                              "name": ref("attributeSets", S_CONFIG, "name")},
                                "relationshipAttributes": [{"leftAttributeName": "CampaignName", "rightAttributeName": "CampaignName"}]}},
            },
            "eventDefinitions": {"ev1": {"data": {"name": "Entry event", "type": "AutomationAudience",
                                                  "eventDefinitionKey": "DEAudience-1",
                                                  "dataExtensionId": ref("dataExtensions", ENTRY, "id")}}},
            "queryActivities": {"q1": {"data": {"name": "Q_Entry", "queryText": sql,
                                                "targetId": ref("dataExtensions", ENTRY, "id"),
                                                "targetUpdateTypeName": "Overwrite"}}},
            "automations": {"a1": {"data": {"name": "A_Entry", "steps": [
                {"activities": [{"name": ref("queryActivities", "q1", "name")}]}]}}},
            "journeys": {"j1": {"data": {
                "name": "Mini journey", "key": "mini", "entryMode": "MultipleEntries",
                "defaults": {"email": ['{{Event.' + ref("eventDefinitions", "ev1", "eventDefinitionKey") + '."Email"}}']},
                "triggers": [{"metaData": {"eventDefinitionId": ref("eventDefinitions", "ev1", "id")}}],
                "activities": activities}}},
        },
        "selectedEntities": {"journeys": ["j1"]},
    }


def write(path: Path) -> Path:
    path.write_text(json.dumps(package()), encoding="utf-8")
    return path
