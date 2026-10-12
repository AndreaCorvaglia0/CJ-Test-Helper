"""Builders for the examples of the spec section "Extensions beyond the pilot (agreed 12 October 2026)".

package.json only; expected.json and README.md are written by hand from docs/spec.md.
Reuses the helpers of examples/build_examples.py, so every package keeps the pilot's shape, and adds the
raw shapes the extension introduces (copied in form only from real exports, with invented names):

- Journey Data conditions: Key="Event.<eventDefinitionKey>.<Field>" with IsEphemeralAttribute="true",
  UiMetaData="{}" and no AttributePath;
- attribute-to-attribute conditions: an empty <Value> plus ValueParameterName="Event.<key>.<Field>";
- Contact Data sets linked to the contact by a group-to-set relationship only (the entry data extension
  outside Contact Builder), and an attribute set whose relationship is missing from the export;
- entry sources: EmailAudience with metaData.scheduleFlowMode "runOnce" (a bare automationId GUID, no
  automation in the export) and CloudPagesSmartCaptureSubmissionEvent;
- journey entryMode OnceAndDone / SingleEntryAcrossAllVersions, journey defaults.mobileNumber;
- Package Manager `issues` on entities.

Run:  python examples/build_extension_examples.py [name ...]
(writes examples/<name>/package.json, then validates package and expected.json like build_examples.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EXAMPLES_DIR))
import build_examples as B  # noqa: E402
from build_examples import (GROUP_NAME, Journey, Package, add_email_asset, add_entry_source, add_journey,  # noqa: E402
                            boolean, criteria, date, export, fld, ref, setup_contact_only, sql_master_only, text)

ZERO_GUID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def key_field(name: str = "SubscriberKey", length: int = 50) -> dict:
    return text(name, length, pk=True, nullable=False)


def email_address(name: str = "EmailAddress") -> dict:
    return fld(name, "EmailAddress", 254)


def number(name: str, **kw) -> dict:
    return fld(name, "Number", None, **kw)


def decimal(name: str, length: int = 18, scale: int = 2, **kw) -> dict:
    f = fld(name, "Decimal", length, **kw)
    f["scale"] = scale
    return f


def entry_table(pkg: Package, name: str, extra: list[dict]) -> None:
    """Entry data extension of a data-extension entry source: sendable on SubscriberKey, like the real exports."""
    pkg.table(name, [key_field(), email_address()] + extra, sendable_field="SubscriberKey")


def log_table(pkg: Package, name: str) -> None:
    """Written-only table (target of every logging Update contact), sendable, outside Contact Builder."""
    pkg.table(name, [key_field(), text("LastAction", 50)], sendable_field="SubscriberKey")


def log(j: Journey, key: str, name: str, table: str, action: str, nxt: str | None) -> None:
    j.update(key, name, table, [("LastAction", action)], nxt)


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

def event_key_ref(event_id: str) -> str:
    return ref("eventDefinitions", event_id, "eventDefinitionKey")


def jd_cond(event_id: str, field: str, operator: str, value: str = "") -> str:
    """A Journey Data condition, written like the real exports (ephemeral attribute, no AttributePath)."""
    return ('<Condition IsEphemeralAttribute="true" Key="Event.%s.%s" Operator="%s" UiMetaData="{}">'
            '<Value><![CDATA[%s]]></Value></Condition>' % (event_key_ref(event_id), field, operator, value))


def attr_cmp_cond(pkg: Package, table: str, field: str, operator: str, value_parameter: str) -> str:
    """Attribute compared with another attribute: empty <Value>, the other side in ValueParameterName.

    `table` must be the first (group-to-set) table of pkg.chain, as in the real export.
    """
    key = "%s.%s" % (ref("attributeSets", pkg.sets[table], "name"), field)
    ui = "{&quot;groupToSetRelationshipId&quot;:&quot;%s&quot;}" % ref(
        "attributeRelationships", pkg.rels[pkg.chain[0]], "id")
    return ('<Condition Key="%s" Operator="%s" UiMetaData="%s" ValueParameterName="%s">'
            '<Value><![CDATA[]]></Value></Condition>' % (key, operator, ui, value_parameter))


# ---------------------------------------------------------------------------
# Entry sources and journey
# ---------------------------------------------------------------------------

def add_de_entry(pkg: Package, journey_name: str, table: str) -> tuple[str, str]:
    """EmailAudience event (data extension entry source), schedule Run Once on publish.

    Like the real exports: arguments.automationId is a bare GUID and no automation is in the package.
    Returns (event id, eventDefinitionKey).
    """
    de_id = pkg.tables[table]
    event_id = pkg.gid("event", journey_name)
    event_key = "DEAudience-" + pkg.gid("event-key", journey_name)
    pkg.add("eventDefinitions", event_id, {
        "name": journey_name, "type": "EmailAudience", "dataExtensionId": ref("dataExtensions", de_id, "id"),
        "description": "", "eventDefinitionKey": event_key, "mode": "Production",
        "iconUrl": "/images/icon-data-extension.svg", "isVisibleInPicker": False, "category": "Audience",
        "disableDEDataLogging": False, "isPlatformObject": False,
        "metaData": {"scheduleState": "No Schedule", "criteriaDescription": None, "scheduleFlowMode": "runOnce",
                     "runOnceScheduleMode": "onPublish"},
        "configurationArguments": {"unconfigured": False},
        "arguments": {"serializedObjectType": 3, "eventDefinitionId": event_id, "eventDefinitionKey": event_key,
                      "dataExtensionId": de_id, "automationId": pkg.gid("jb-scheduler", journey_name),
                      "criteria": "", "useHighWatermark": False},
        "sourceApplicationExtensionId": "97e942ee-6914-4d3d-9e52-37ecb71f79ed"})
    return event_id, event_key


def add_cloudpages_entry(pkg: Package, journey_name: str, table: str, form_id: int = 4242) -> tuple[str, str]:
    """CloudPagesSmartCaptureSubmissionEvent bound to the form's data extension. Returns (event id, key)."""
    de_id = pkg.tables[table]
    event_id = pkg.gid("event", journey_name)
    event_key = "CloudPagesSma-" + pkg.gid("event-key", journey_name)
    icon = "https://cloudpages-jb-event.example.com/images/icon.svg"
    pkg.add("eventDefinitions", event_id, {
        "name": journey_name, "type": "CloudPagesSmartCaptureSubmissionEvent",
        "dataExtensionId": ref("dataExtensions", de_id, "id"), "description": "", "eventDefinitionKey": event_key,
        "mode": "Production", "iconUrl": icon, "isVisibleInPicker": False, "category": "Event",
        "disableDEDataLogging": False, "isPlatformObject": False,
        "metaData": {"icon": icon, "original_icon": "images/icon.svg", "criteriaDescription": "",
                     "scheduleState": "No Schedule"},
        "configurationArguments": {"applicationExtensionKey": "cloudpages-jb-event-smart-capture",
                                   "smartCaptureFormID": form_id},
        "arguments": {"serializedObjectType": 0, "dataTargetName": table, "formName": "EX_Feedback_Form",
                      "useHighWatermark": False, "eventDefinitionId": event_id, "eventDefinitionKey": event_key,
                      "dataExtensionId": de_id, "criteria": ""},
        "sourceApplicationExtensionId": pkg.gid("app-extension", "cloudpages")})
    return event_id, event_key


def add_journey_ext(pkg: Package, journey: Journey, event_id: str, trigger_type: str,
                    entry_mode: str = "MultipleEntries", email_field: str = "EmailAddress",
                    mobile_field: str | None = None, issues: list | None = None) -> None:
    """Journey entity for a non-automation entry source (shapes of the real exports)."""
    jid = pkg.gid("journey", journey.name)
    pkg.journey_id = jid
    key_ref = event_key_ref(event_id)
    defaults: dict = {"email": ['{{Event.%s."%s"}}' % (key_ref, email_field)]}
    if mobile_field:
        defaults["mobileNumber"] = ['{{Event.%s."%s"}}' % (key_ref, mobile_field)]
    defaults["properties"] = {"analyticsTracking": {"enabled": False, "analyticsType": "google",
                                                    "urlDomainsToTrack": []}}
    trigger_args = {"startActivityKey": "{{Context.StartActivityKey}}", "dequeueReason": "{{Context.DequeueReason}}",
                    "lastExecutedActivityKey": "{{Context.LastExecutedActivityKey}}", "filterResult": "true"}
    if trigger_type == "CloudPagesSmartCaptureSubmissionEvent":
        event = pkg.entities["eventDefinitions"][event_id]["data"]
        config = dict(event["configurationArguments"])
        config.update({"filterDefinitionId": ZERO_GUID, "criteria": "", "schemaVersionId": 0})
        meta = {"chainType": "None", "configurationRequired": False,
                "entrySourceGroupConfigUrl": "https://cloudpages-jb-event.example.com/entrysourcegroupconfig.json",
                "eventDefinitionId": ref("eventDefinitions", event_id, "id"), "eventDefinitionKey": key_ref,
                "iconUrl": event["iconUrl"], "title": ""}
        name = "TRIGGER"
    else:
        config = {"filterDefinitionId": ZERO_GUID, "criteria": "", "schemaVersionId": 0}
        meta = {"category": "Audience", "chainType": "None", "configurationRequired": False,
                "entrySourceGroupConfigUrl": "jb:///data/entry/audience/entrysourcegroupconfig.json",
                "eventDefinitionId": ref("eventDefinitions", event_id, "id"), "eventDefinitionKey": key_ref,
                "iconUrl": "/images/icon-data-extension.svg", "title": "Data Extension"}
        name = journey.name
    pkg.add("journeys", jid, {
        "name": journey.name, "key": pkg.gid("journey-key", journey.name), "workflowApiVersion": 1,
        "description": "", "channel": "", "defaults": defaults, "definitionType": "Multistep",
        "entryMode": entry_mode, "executionMode": "Production", "exits": [], "goals": [],
        "metaData": {"highThroughputSending": {"email": False}},
        "triggers": [{"arguments": trigger_args, "configurationArguments": config, "description": "",
                      "id": pkg.gid("trigger", journey.name), "key": "TRIGGER", "metaData": meta, "name": name,
                      "outcomes": [], "type": trigger_type}],
        "activities": journey.activities, "version": 1})
    if issues:
        pkg.entities["journeys"][jid]["issues"] = issues


def group_to_set(pkg: Package, table: str, field: str = "SubscriberKey") -> None:
    """One attribute set linked to the contact by a group-to-set relationship on `field` (real exports' shape)."""
    pkg.contact_model([(table, field, "")])


# ---------------------------------------------------------------------------
# The examples
# ---------------------------------------------------------------------------

def build_journey_data_split() -> dict:
    pkg = Package("journey_data_split", "EX journey data split")
    score = decimal("Score")
    entry_table(pkg, "DE_JD_Entry", [text("Segment", 20), score, boolean("HasConsent")])
    log_table(pkg, "DE_JD_Log")
    j = Journey(pkg, "EX_JourneyDataSplit")
    event_id, _ = add_de_entry(pkg, j.name, "DE_JD_Entry")
    j.decision("SPLIT-1", "Key missing?", [
        ("path_a", "no key", criteria(jd_cond(event_id, "SubscriberKey", "IsNull")), None, "SubscriberKey is null"),
        ("remainder_path", "key present", None, "SPLIT-2", None)])
    j.decision("SPLIT-2", "Consent", [
        ("path_a", "true", criteria(jd_cond(event_id, "HasConsent", "Is", "true")), "SPLIT-3", "HasConsent is True"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    j.decision("SPLIT-3", "Segment and score", [
        ("path_a", "Premium", criteria(jd_cond(event_id, "Segment", "Equal", "Premium")), "UPDATE-1",
         "Segment equal Premium"),
        ("path_b", "High score", criteria(jd_cond(event_id, "Score", "GreaterThan", "50")), "UPDATE-2",
         "Score greater than 50"),
        ("remainder_path", "Remainder", None, "UPDATE-4", None)])
    log(j, "UPDATE-1", "Premium offer", "DE_JD_Log", "Premium", None)
    log(j, "UPDATE-2", "Score offer", "DE_JD_Log", "Score", None)
    log(j, "UPDATE-3", "No consent", "DE_JD_Log", "NoConsent", None)
    log(j, "UPDATE-4", "Standard offer", "DE_JD_Log", "Standard", None)
    add_journey_ext(pkg, j, event_id, "EmailAudience")
    return export(pkg)


def build_journey_data_snapshot() -> dict:
    pkg = Package("journey_data_snapshot", "EX journey data snapshot")
    entry_table(pkg, "DE_Snap_Entry", [text("Tier", 20)])
    log_table(pkg, "DE_Snap_Log")
    group_to_set(pkg, "DE_Snap_Entry")          # the entry table is also Contact Data
    j = Journey(pkg, "EX_JourneyDataSnapshot")
    event_id, _ = add_de_entry(pkg, j.name, "DE_Snap_Entry")
    j.decision("SPLIT-1", "Tier at entry", [
        ("path_a", "Gold", criteria(jd_cond(event_id, "Tier", "Equal", "Gold")), "UPDATE-1", "Tier equal Gold"),
        ("remainder_path", "Remainder", None, "UPDATE-4", None)])
    j.update("UPDATE-1", "Downgrade to Silver", "DE_Snap_Entry", [("Tier", "Silver")], "SPLIT-2")
    j.decision("SPLIT-2", "Tier from journey data", [
        ("path_a", "Gold", criteria(jd_cond(event_id, "Tier", "Equal", "Gold")), "SPLIT-3", "Tier equal Gold"),
        ("remainder_path", "Remainder", None, None, None)])
    j.decision("SPLIT-3", "Tier from contact data", [
        ("path_a", "Silver", criteria(pkg.cond("DE_Snap_Entry", "Tier", "Equal", "Silver")), "UPDATE-2",
         "Tier equal Silver"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    log(j, "UPDATE-2", "Live value seen", "DE_Snap_Log", "LiveSeen", None)
    log(j, "UPDATE-3", "Live value missed", "DE_Snap_Log", "LiveMissed", None)
    log(j, "UPDATE-4", "Not gold", "DE_Snap_Log", "NotGold", None)
    add_journey_ext(pkg, j, event_id, "EmailAudience")
    return export(pkg)


def build_between_inclusive() -> dict:
    pkg = Package("between_inclusive", "EX between inclusive")
    setup_contact_only(pkg, [number("Score")])
    m = "DE_Master"
    j = Journey(pkg, "EX_BetweenInclusive")
    j.decision("SPLIT-1", "Score band", [
        ("path_a", "High", criteria(pkg.cond(m, "Score", "GreaterThan", "20")), "UPDATE-1", "Score greater than 20"),
        # Salesforce truncates the description of a Between ("between 10"); the XML value is the truth.
        ("path_b", "Mid", criteria(pkg.cond(m, "Score", "Between", "10|20")), "UPDATE-2", "Score between 10"),
        ("path_c", "Twenty", criteria(pkg.cond(m, "Score", "Equal", "20")), "UPDATE-3", "Score equal 20"),
        ("remainder_path", "Low", None, "UPDATE-4", None)])
    B.log_update(j, "UPDATE-1", "High score", "High", None)
    B.log_update(j, "UPDATE-2", "Mid score", "Mid", None)
    B.log_update(j, "UPDATE-3", "Score twenty", "Twenty", None)
    B.log_update(j, "UPDATE-4", "Low score", "Low", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_BetweenInclusive_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


def build_row_absent_isnull() -> dict:
    pkg = Package("row_absent_isnull", "EX row absent isnull")
    entry_table(pkg, "DE_RA_Entry", [])
    pkg.table("DE_RA_Form", [key_field(), boolean("Consent"), date("SubmittedOn")], sendable_field="SubscriberKey")
    log_table(pkg, "DE_RA_Log")
    group_to_set(pkg, "DE_RA_Form")
    f = "DE_RA_Form"
    j = Journey(pkg, "EX_RowAbsentIsNull")
    event_id, _ = add_de_entry(pkg, j.name, "DE_RA_Entry")
    j.decision("SPLIT-1", "Form submitted?", [
        ("path_a", "not submitted", criteria(pkg.cond(f, "SubscriberKey", "IsNull", "")), "UPDATE-1",
         "SubscriberKey is null"),
        ("remainder_path", "submitted", None, "SPLIT-2", None)])
    j.decision("SPLIT-2", "Consent", [
        ("path_a", "true", criteria(pkg.cond(f, "Consent", "Is", "true")), "UPDATE-2", "Consent is True"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    log(j, "UPDATE-1", "No form", "DE_RA_Log", "NoForm", None)
    log(j, "UPDATE-2", "Consent given", "DE_RA_Log", "Consent", None)
    log(j, "UPDATE-3", "No consent", "DE_RA_Log", "NoConsent", None)
    add_journey_ext(pkg, j, event_id, "EmailAudience")
    return export(pkg)


def build_row_absent_attribute_comparison() -> dict:
    pkg = Package("row_absent_attribute_comparison", "EX row absent attribute comparison")
    entry_table(pkg, "DE_AC_Entry", [])
    pkg.table("DE_AC_Optin", [key_field(), text("Channel", 20)], sendable_field="SubscriberKey")
    log_table(pkg, "DE_AC_Log")
    group_to_set(pkg, "DE_AC_Optin")
    o = "DE_AC_Optin"
    j = Journey(pkg, "EX_RowAbsentAttributeComparison")
    event_id, event_key = add_de_entry(pkg, j.name, "DE_AC_Entry")
    same_key = attr_cmp_cond(pkg, o, "SubscriberKey", "Equal", "Event.%s.SubscriberKey" % event_key)
    j.decision("SPLIT-1", "Opt-in on file?", [
        ("path_a", "on file", criteria(same_key), "SPLIT-2", "SubscriberKey equal SubscriberKey"),
        ("remainder_path", "not on file", None, "UPDATE-3", None)])
    j.decision("SPLIT-2", "Channel", [
        ("path_a", "SMS", criteria(pkg.cond(o, "Channel", "Equal", "SMS")), "UPDATE-1", "Channel equal SMS"),
        ("remainder_path", "Remainder", None, "UPDATE-2", None)])
    log(j, "UPDATE-1", "SMS opt-in", "DE_AC_Log", "Sms", None)
    log(j, "UPDATE-2", "Other opt-in", "DE_AC_Log", "OtherChannel", None)
    log(j, "UPDATE-3", "No opt-in", "DE_AC_Log", "NoOptin", None)
    add_journey_ext(pkg, j, event_id, "EmailAudience")
    return export(pkg)


def build_attribute_comparison_unsupported() -> dict:
    pkg = Package("attribute_comparison_unsupported", "EX attribute comparison unsupported")
    entry_table(pkg, "DE_AU_Entry", [text("PreferredChannel", 20)])
    pkg.table("DE_AU_Prefs", [key_field(), boolean("Active"), text("LastChannel", 20)], sendable_field="SubscriberKey")
    log_table(pkg, "DE_AU_Log")
    group_to_set(pkg, "DE_AU_Prefs")
    p = "DE_AU_Prefs"
    j = Journey(pkg, "EX_AttributeComparisonUnsupported")
    event_id, event_key = add_de_entry(pkg, j.name, "DE_AU_Entry")
    two_fields = attr_cmp_cond(pkg, p, "LastChannel", "Equal", "Event.%s.PreferredChannel" % event_key)
    j.decision("SPLIT-1", "Active", [
        ("path_a", "true", criteria(pkg.cond(p, "Active", "Is", "true")), "SPLIT-2", "Active is True"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    j.decision("SPLIT-2", "Same channel?", [
        ("path_a", "same", criteria(two_fields), "UPDATE-1", "LastChannel equal PreferredChannel"),
        ("remainder_path", "different", None, "UPDATE-2", None)])
    log(j, "UPDATE-1", "Same channel", "DE_AU_Log", "Same", None)
    log(j, "UPDATE-2", "Channel changed", "DE_AU_Log", "Changed", None)
    log(j, "UPDATE-3", "Inactive", "DE_AU_Log", "Inactive", None)
    add_journey_ext(pkg, j, event_id, "EmailAudience")
    return export(pkg)


def build_missing_relationship() -> dict:
    pkg = Package("missing_relationship", "EX missing relationship")
    entry_table(pkg, "DE_MR_Entry", [text("Channel", 20)])
    pkg.table("DE_MR_Consent", [text("SubscriberKey", 254, pk=True, nullable=False), boolean("DoNotTrack")])
    log_table(pkg, "DE_MR_Log")
    # Attribute group and set, but no attributeRelationships entity: the set's leftRelationships and the
    # condition's groupToSetRelationshipId name a relationship id that is not in the export (literal GUIDs,
    # as in the real export, since an {{mcpm#...}} reference would have nothing to resolve to).
    missing = pkg.gid("rel", "missing relationship")
    pkg.group_id = pkg.gid("group", GROUP_NAME)
    pkg.add("attributeGroups", pkg.group_id, {
        "attributeGroupIconKey": "et-icon-envelop", "attributeGroupType": "Standard",
        "definitionName": {"value": GROUP_NAME}, "name": GROUP_NAME, "isSystemDefined": False})
    de_id = pkg.tables["DE_MR_Consent"]
    set_id = pkg.gid("set", "DE_MR_Consent")
    pkg.add("attributeSets", set_id, {
        "storageLogicalType": "DataExtension", "isRoot": False,
        "storageName": ref("dataExtensions", de_id, "name"),
        "storageReferenceID": {"type": "guid", "value": ref("dataExtensions", de_id, "id")},
        "groupId": ref("attributeGroups", pkg.group_id, "id"), "name": "DE_MR_Consent",
        "leftRelationships": ["#/entities/attributeRelationships/%s/data" % missing], "isSystemDefined": False})
    dnt = ('<Condition Key="%s.DoNotTrack" Operator="Is" UiMetaData="{&quot;groupToSetRelationshipId&quot;:'
           '&quot;%s&quot;}"><Value><![CDATA[false]]></Value></Condition>'
           % (ref("attributeSets", set_id, "name"), missing))
    j = Journey(pkg, "EX_MissingRelationship")
    event_id, _ = add_de_entry(pkg, j.name, "DE_MR_Entry")
    j.decision("SPLIT-1", "Channel", [
        ("path_a", "Email", criteria(jd_cond(event_id, "Channel", "Equal", "Email")), "SPLIT-2", "Channel equal Email"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    j.decision("SPLIT-2", "Do not track", [
        ("path_a", "tracking allowed", criteria(dnt), "UPDATE-1", "DoNotTrack is False"),
        ("remainder_path", "Remainder", None, "UPDATE-2", None)])
    log(j, "UPDATE-1", "Tracked email", "DE_MR_Log", "Tracked", None)
    log(j, "UPDATE-2", "Untracked email", "DE_MR_Log", "Untracked", None)
    log(j, "UPDATE-3", "Other channel", "DE_MR_Log", "OtherChannel", None)
    issue = {"type": "ENTITY_NOT_FOUND", "level": "WARNING",
             "cause": {"type": "ATTRIBUTE_GROUP", "level": "ERROR", "message": "Unable to find attribute relationship",
                       "data": {"retrievalProperty": "id", "value": missing}},
             "sourceJobType": "PACKAGE", "task": {"isComplete": False},
             "entity": {"entityType": "attributeRelationships", "retrievalProperty": "id", "value": missing,
                        "parentPath": "$['activities'][1]['configurationArguments']['criteria']['path_a']:I120",
                        "locationInformation": {"activityName": "Do not track", "activityNumber": 2,
                                                "activityType": "MULTICRITERIADECISION",
                                                "dependencyContentType": "JOURNEY_ACTIVITY",
                                                "parentJourneyName": j.name}}}
    add_journey_ext(pkg, j, event_id, "EmailAudience", issues=[issue])
    # An INFO issue on a table the journey uses: below the "warning or error" level, so not listed.
    pkg.entities["dataExtensions"][pkg.tables["DE_MR_Entry"]]["issues"] = [
        {"type": "UNSUPPORTED_AMPSCRIPT", "level": "INFO", "sourceJobType": "PACKAGE", "issue": "UNRESOLVED_VARIABLE"}]
    return export(pkg)


def build_run_once_entry() -> dict:
    pkg = Package("run_once_entry", "EX run once entry")
    entry_table(pkg, "DE_RO_Entry", [boolean("Optin")])
    log_table(pkg, "DE_RO_Log")
    j = Journey(pkg, "EX_RunOnceEntry")
    event_id, _ = add_de_entry(pkg, j.name, "DE_RO_Entry")
    j.decision("SPLIT-1", "Opt-in", [
        ("path_a", "true", criteria(jd_cond(event_id, "Optin", "Is", "true")), "UPDATE-1", "Optin is True"),
        ("remainder_path", "Remainder", None, "UPDATE-2", None)])
    log(j, "UPDATE-1", "Opted in", "DE_RO_Log", "OptedIn", None)
    log(j, "UPDATE-2", "Not opted in", "DE_RO_Log", "NotOptedIn", None)
    add_journey_ext(pkg, j, event_id, "EmailAudience")
    return export(pkg)


def build_cloudpages_entry() -> dict:
    pkg = Package("cloudpages_entry", "EX cloudpages entry")
    pkg.table("DE_CP_Submissions", [key_field(), text("FirstName", 50), email_address("Email"), boolean("Consent")],
              sendable_field="SubscriberKey")
    log_table(pkg, "DE_CP_Log")
    j = Journey(pkg, "EX_CloudPagesEntry")
    event_id, _ = add_cloudpages_entry(pkg, j.name, "DE_CP_Submissions")
    j.decision("SPLIT-1", "Consent", [
        ("path_a", "true", criteria(jd_cond(event_id, "Consent", "Is", "true")), "UPDATE-1", "Consent is True"),
        ("remainder_path", "Remainder", None, "UPDATE-2", None)])
    log(j, "UPDATE-1", "Consent given", "DE_CP_Log", "Consent", None)
    log(j, "UPDATE-2", "No consent", "DE_CP_Log", "NoConsent", None)
    issue = {"type": "UNSUPPORTED_FUNCTIONALITY", "level": "WARNING", "sourceJobType": "PACKAGE",
             "functionality": "JOURNEY_UNSUPPORTED_ENTRY"}
    add_journey_ext(pkg, j, event_id, "CloudPagesSmartCaptureSubmissionEvent", email_field="Email", issues=[issue])
    return export(pkg)


def build_engagement_short_window() -> dict:
    pkg = Package("engagement_short_window", "EX engagement short window")
    setup_contact_only(pkg, [boolean("Perm")])
    add_email_asset(pkg, "900801", "Flash Offer", "FLASH OFFER", with_link=True)
    add_email_asset(pkg, "900802", "Slow Digest", "SLOW DIGEST", with_link=True)
    j = Journey(pkg, "EX_EngagementShortWindow")
    j.decision("SPLIT-1", "Permission", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "Perm", "Is", "true")), "EMAIL-1", "Perm is True"),
        ("remainder_path", "Remainder", None, "EMAIL-2", None)])
    j.email("EMAIL-1", "900801", "WAIT-1")
    j.wait_duration("WAIT-1", "ENGAGE-1", 5, "MINUTES")
    j.engagement("ENGAGE-1", "Open Flash Offer", "open", "EMAIL-1", "Flash Offer", yes_next=None, no_next=None)
    j.email("EMAIL-2", "900802", "WAIT-2")
    j.wait_duration("WAIT-2", "ENGAGE-2", 2, "DAYS")
    j.engagement("ENGAGE-2", "Open Slow Digest", "open", "EMAIL-2", "Slow Digest", yes_next=None, no_next=None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_EngagementShortWindow_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


def build_update_inserts_row() -> dict:
    pkg = Package("update_inserts_row", "EX update inserts row")
    entry_table(pkg, "DE_UI_Entry", [])
    pkg.table("DE_UI_Visit", [key_field(), text("Source", 20), date("VisitedOn")], sendable_field="SubscriberKey")
    log_table(pkg, "DE_UI_Log")
    group_to_set(pkg, "DE_UI_Visit")
    v = "DE_UI_Visit"
    j = Journey(pkg, "EX_UpdateInsertsRow")
    event_id, _ = add_de_entry(pkg, j.name, "DE_UI_Entry")
    j.decision("SPLIT-1", "Visit on file?", [
        ("path_a", "no visit", criteria(pkg.cond(v, "SubscriberKey", "IsNull", "")), "UPDATE-1", "SubscriberKey is null"),
        ("remainder_path", "visit on file", None, "UPDATE-3", None)])
    j.update("UPDATE-1", "Record visit", v, [("Source", "Journey"), ("VisitedOn", "{{DateTime.Now}}")], "SPLIT-2")
    j.decision("SPLIT-2", "Visit recorded?", [
        ("path_a", "still missing", criteria(pkg.cond(v, "SubscriberKey", "IsNull", "")), "UPDATE-2",
         "SubscriberKey is null"),
        ("remainder_path", "recorded", None, "UPDATE-4", None)])
    log(j, "UPDATE-2", "Visit still missing", "DE_UI_Log", "StillMissing", None)
    log(j, "UPDATE-3", "Returning visitor", "DE_UI_Log", "Returning", None)
    log(j, "UPDATE-4", "Visit recorded", "DE_UI_Log", "Recorded", None)
    add_journey_ext(pkg, j, event_id, "EmailAudience")
    return export(pkg)


# -- further constructs of the extension section --------------------------------------------------

def build_journey_data_other_event() -> dict:
    pkg = Package("journey_data_other_event", "EX journey data other event")
    entry_table(pkg, "DE_OE_Entry", [boolean("Optin")])
    entry_table(pkg, "DE_OE_Archive", [text("Segment", 20)])
    log_table(pkg, "DE_OE_Log")
    j = Journey(pkg, "EX_JourneyDataOtherEvent")
    other_id, _ = add_de_entry(pkg, "EX_JourneyDataOtherEvent_Archive", "DE_OE_Archive")   # not the trigger's
    event_id, _ = add_de_entry(pkg, j.name, "DE_OE_Entry")
    j.decision("SPLIT-1", "Opt-in", [
        ("path_a", "true", criteria(jd_cond(event_id, "Optin", "Is", "true")), "SPLIT-2", "Optin is True"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    j.decision("SPLIT-2", "Archived segment", [
        ("path_a", "Gold", criteria(jd_cond(other_id, "Segment", "Equal", "Gold")), "UPDATE-1", "Segment equal Gold"),
        ("remainder_path", "Remainder", None, "UPDATE-2", None)])
    log(j, "UPDATE-1", "Gold archive", "DE_OE_Log", "GoldArchive", None)
    log(j, "UPDATE-2", "Other archive", "DE_OE_Log", "OtherArchive", None)
    log(j, "UPDATE-3", "Not opted in", "DE_OE_Log", "NotOptedIn", None)
    add_journey_ext(pkg, j, event_id, "EmailAudience")
    return export(pkg)


def build_row_absent_other_fields() -> dict:
    pkg = Package("row_absent_other_fields", "EX row absent other fields")
    entry_table(pkg, "DE_PF_Entry", [])
    pkg.table("DE_PF_Profile", [key_field(), text("Nickname", 20)], sendable_field="SubscriberKey")
    log_table(pkg, "DE_PF_Log")
    group_to_set(pkg, "DE_PF_Profile")
    p = "DE_PF_Profile"
    j = Journey(pkg, "EX_RowAbsentOtherFields")
    event_id, _ = add_de_entry(pkg, j.name, "DE_PF_Entry")
    j.decision("SPLIT-1", "Has profile?", [
        ("path_a", "profile", criteria(pkg.cond(p, "SubscriberKey", "IsNotNull", "")), "UPDATE-1",
         "SubscriberKey is not null"),
        ("remainder_path", "no profile", None, "SPLIT-2", None)])
    j.decision("SPLIT-2", "Nickname", [
        ("path_a", "empty", criteria(pkg.cond(p, "Nickname", "IsNull", "")), "UPDATE-2", "Nickname is null"),
        ("path_b", "Bob", criteria(pkg.cond(p, "Nickname", "Equal", "Bob")), "UPDATE-3", "Nickname equal Bob"),
        ("remainder_path", "Remainder", None, "UPDATE-4", None)])
    log(j, "UPDATE-1", "Profile found", "DE_PF_Log", "Profile", None)
    log(j, "UPDATE-2", "Nickname empty", "DE_PF_Log", "NicknameEmpty", None)
    log(j, "UPDATE-3", "Nickname Bob", "DE_PF_Log", "NicknameBob", None)
    log(j, "UPDATE-4", "Nickname other", "DE_PF_Log", "NicknameOther", None)
    add_journey_ext(pkg, j, event_id, "EmailAudience")
    return export(pkg)


def _entry_mode_package(example: str, journey_name: str, entry_mode: str) -> dict:
    """Automation entry (the pilot's procedure) with a given journey entryMode."""
    pkg = Package(example, "EX " + example.replace("_", " "))
    setup_contact_only(pkg, [boolean("Perm")])
    j = Journey(pkg, journey_name)
    j.decision("SPLIT-1", "Permission", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "Perm", "Is", "true")), "UPDATE-1", "Perm is True"),
        ("remainder_path", "Remainder", None, "UPDATE-2", None)])
    B.log_update(j, "UPDATE-1", "Allowed", "Allowed", None)
    B.log_update(j, "UPDATE-2", "Not allowed", "NotAllowed", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_%s_Entry" % journey_name, sql_master_only(pkg))
    add_journey(pkg, j, event)
    pkg.entities["journeys"][pkg.journey_id]["data"]["entryMode"] = entry_mode
    return export(pkg)


def build_once_and_done_entry() -> dict:
    return _entry_mode_package("once_and_done_entry", "EX_OnceAndDoneEntry", "OnceAndDone")


def build_single_entry_all_versions() -> dict:
    return _entry_mode_package("single_entry_all_versions", "EX_SingleEntryAllVersions",
                               "SingleEntryAcrossAllVersions")


def build_default_missing_column() -> dict:
    pkg = Package("default_missing_column", "EX default missing column")
    entry_table(pkg, "DE_DM_Entry", [boolean("Optin")])
    log_table(pkg, "DE_DM_Log")
    j = Journey(pkg, "EX_DefaultMissingColumn")
    event_id, _ = add_de_entry(pkg, j.name, "DE_DM_Entry")
    j.decision("SPLIT-1", "Opt-in", [
        ("path_a", "true", criteria(jd_cond(event_id, "Optin", "Is", "true")), "UPDATE-1", "Optin is True"),
        ("remainder_path", "Remainder", None, "UPDATE-2", None)])
    log(j, "UPDATE-1", "Opted in", "DE_DM_Log", "OptedIn", None)
    log(j, "UPDATE-2", "Not opted in", "DE_DM_Log", "NotOptedIn", None)
    # defaults.mobileNumber names MobilePhone, a column DE_DM_Entry does not have.
    add_journey_ext(pkg, j, event_id, "EmailAudience", mobile_field="MobilePhone")
    return export(pkg)


def build_unused_asset() -> dict:
    pkg = Package("unused_asset", "EX unused asset")
    entry_table(pkg, "DE_UA_Entry", [boolean("Optin")])
    log_table(pkg, "DE_UA_Log")
    # Two assets no activity uses: an image without fileProperties, and an old email whose HTML references the
    # image's publishedURL, a path the image does not have (the shape behind the asset warnings of the real exports).
    banner = "900911"
    pkg.add("assets", banner, {"assetType": {"id": 28, "name": "png", "displayName": "Image"},
                               "customerKey": pkg.gid("asset-key", banner), "name": "EX_Unused_Banner.png",
                               "description": "", "contentType": "image/png"})
    add_email_asset(pkg, "900912", "Old Newsletter", "OLD NEWSLETTER", with_link=True)
    view = pkg.entities["assets"]["900912"]["data"]["views"]["html"]
    view["content"] = view["content"].replace(
        "<body>", '<body><img src="%s" alt="banner" />' % ref("assets", banner, "fileProperties/publishedURL"))
    j = Journey(pkg, "EX_UnusedAsset")
    event_id, _ = add_de_entry(pkg, j.name, "DE_UA_Entry")
    j.decision("SPLIT-1", "Opt-in", [
        ("path_a", "true", criteria(jd_cond(event_id, "Optin", "Is", "true")), "UPDATE-1", "Optin is True"),
        ("remainder_path", "Remainder", None, "UPDATE-2", None)])
    log(j, "UPDATE-1", "Opted in", "DE_UA_Log", "OptedIn", None)
    log(j, "UPDATE-2", "Not opted in", "DE_UA_Log", "NotOptedIn", None)
    add_journey_ext(pkg, j, event_id, "EmailAudience")
    return export(pkg)


EXTENSION = {
    "journey_data_split": build_journey_data_split,
    "journey_data_snapshot": build_journey_data_snapshot,
    "between_inclusive": build_between_inclusive,
    "row_absent_isnull": build_row_absent_isnull,
    "row_absent_attribute_comparison": build_row_absent_attribute_comparison,
    "attribute_comparison_unsupported": build_attribute_comparison_unsupported,
    "missing_relationship": build_missing_relationship,
    "run_once_entry": build_run_once_entry,
    "cloudpages_entry": build_cloudpages_entry,
    "engagement_short_window": build_engagement_short_window,
    "update_inserts_row": build_update_inserts_row,
    "journey_data_other_event": build_journey_data_other_event,
    "row_absent_other_fields": build_row_absent_other_fields,
    "once_and_done_entry": build_once_and_done_entry,
    "single_entry_all_versions": build_single_entry_all_versions,
    "default_missing_column": build_default_missing_column,
    "unused_asset": build_unused_asset,
}


def main(names=None) -> int:
    names = names or list(EXTENSION)
    for name in names:
        d = EXAMPLES_DIR / name
        d.mkdir(exist_ok=True)
        (d / "package.json").write_text(json.dumps(EXTENSION[name](), indent=1, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
    for name in names:
        d = EXAMPLES_DIR / name
        branches = B.validate_package(d / "package.json")
        if (d / "expected.json").exists():
            B.validate_expected(d / "expected.json", branches)
        print("ok  %-34s %3d split branches %s" % (name, len(branches), branches))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
