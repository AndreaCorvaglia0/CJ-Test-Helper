"""Source-independent model of a journey and the data it touches.

Both input adapters (Package Manager export, SFMC API) produce a `Package`;
everything downstream works only on this model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DEField:
    name: str
    type: str
    length: int | None
    is_primary_key: bool
    is_nullable: bool
    default: str | None


@dataclass
class DataExtension:
    name: str
    customer_key: str
    fields: list[DEField]
    is_sendable: bool = False
    sendable_field: str | None = None

    def field(self, name: str) -> DEField | None:
        low = name.lower()
        return next((f for f in self.fields if f.name.lower() == low), None)

    @property
    def primary_key(self) -> list[str]:
        return [f.name for f in self.fields if f.is_primary_key]


@dataclass
class Relationship:
    """Contact Builder relationship. `left_de` is None when the left side is the attribute group root."""
    name: str
    left_de: str | None
    right_de: str
    left_field: str | None
    right_field: str
    left_cardinality: str
    right_cardinality: str


@dataclass
class Outcome:
    key: str
    label: str
    next: str | None
    criteria: Any = None          # criteria.Group | None
    arguments: dict = field(default_factory=dict)


@dataclass
class Activity:
    key: str
    type: str
    name: str
    outcomes: list[Outcome]
    config: dict
    arguments: dict


@dataclass
class EventDefinition:
    id: str
    name: str
    type: str
    event_key: str
    de_name: str | None


@dataclass
class Journey:
    name: str
    key: str
    entry_mode: str
    activities: dict[str, Activity]
    root: str
    defaults: dict
    event_definition_id: str | None


@dataclass
class QueryActivity:
    name: str
    sql: str
    target_de: str | None
    update_type: str


@dataclass
class Automation:
    name: str
    activity_names: list[str]


@dataclass
class Package:
    des: dict[str, DataExtension]
    relationships: list[Relationship]
    contact_root_de: str | None
    contact_key_field: str | None
    journey: Journey
    event_definitions: dict[str, EventDefinition]
    queries: list[QueryActivity]
    automations: list[Automation]
    warnings: list[str] = field(default_factory=list)

    @property
    def entry_de(self) -> str | None:
        ev = self.event_definitions.get(self.journey.event_definition_id or "")
        return ev.de_name if ev else None
