from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class MetadataFieldType(str, Enum):
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    LIST = "LIST"


class MetadataDefinitionScope(str, Enum):
    GLOBAL = "GLOBAL"
    INVENTORY_TYPE = "INVENTORY_TYPE"
    INVENTORY = "INVENTORY"


class InventoryContainerType(str, Enum):
    INVENTORY = "INVENTORY"
    CHECKLIST = "CHECKLIST"


class MetadataFilterOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    BETWEEN = "between"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


@dataclass(frozen=True)
class MetadataFieldTypeSpec:
    value_column: str
    supports_full_text: bool
    supported_filter_operators: tuple[MetadataFilterOperator, ...]


METADATA_DEFINITIONS_TABLE: Final[str] = "metadata_definitions"
METADATA_DEFINITION_ASSIGNMENTS_TABLE: Final[str] = "metadata_definition_assignments"
ITEM_METADATA_VALUES_TABLE: Final[str] = "item_metadata_values"

METADATA_DEFINITION_UNIQUE_KEY: Final[tuple[str]] = ("key",)
ITEM_METADATA_VALUE_UNIQUE_SCOPE: Final[tuple[str, str]] = ("item_id", "definition_id")

METADATA_VALUE_TEXT_COLUMN: Final[str] = "value_text"
METADATA_VALUE_NUMBER_COLUMN: Final[str] = "value_number"
METADATA_VALUE_BOOLEAN_COLUMN: Final[str] = "value_boolean"
METADATA_VALUE_DATE_COLUMN: Final[str] = "value_date"

METADATA_FIELD_TYPE_SPECS: Final[dict[MetadataFieldType, MetadataFieldTypeSpec]] = {
    MetadataFieldType.TEXT: MetadataFieldTypeSpec(
        value_column=METADATA_VALUE_TEXT_COLUMN,
        supports_full_text=True,
        supported_filter_operators=(
            MetadataFilterOperator.EQUALS,
            MetadataFilterOperator.NOT_EQUALS,
            MetadataFilterOperator.CONTAINS,
            MetadataFilterOperator.NOT_CONTAINS,
            MetadataFilterOperator.IS_NULL,
            MetadataFilterOperator.IS_NOT_NULL,
        ),
    ),
    MetadataFieldType.NUMBER: MetadataFieldTypeSpec(
        value_column=METADATA_VALUE_NUMBER_COLUMN,
        supports_full_text=False,
        supported_filter_operators=(
            MetadataFilterOperator.EQUALS,
            MetadataFilterOperator.NOT_EQUALS,
            MetadataFilterOperator.GREATER_THAN,
            MetadataFilterOperator.GREATER_THAN_OR_EQUAL,
            MetadataFilterOperator.LESS_THAN,
            MetadataFilterOperator.LESS_THAN_OR_EQUAL,
            MetadataFilterOperator.BETWEEN,
            MetadataFilterOperator.IS_NULL,
            MetadataFilterOperator.IS_NOT_NULL,
        ),
    ),
    MetadataFieldType.BOOLEAN: MetadataFieldTypeSpec(
        value_column=METADATA_VALUE_BOOLEAN_COLUMN,
        supports_full_text=False,
        supported_filter_operators=(
            MetadataFilterOperator.EQUALS,
            MetadataFilterOperator.NOT_EQUALS,
            MetadataFilterOperator.IS_NULL,
            MetadataFilterOperator.IS_NOT_NULL,
        ),
    ),
    MetadataFieldType.DATE: MetadataFieldTypeSpec(
        value_column=METADATA_VALUE_DATE_COLUMN,
        supports_full_text=False,
        supported_filter_operators=(
            MetadataFilterOperator.EQUALS,
            MetadataFilterOperator.NOT_EQUALS,
            MetadataFilterOperator.GREATER_THAN,
            MetadataFilterOperator.GREATER_THAN_OR_EQUAL,
            MetadataFilterOperator.LESS_THAN,
            MetadataFilterOperator.LESS_THAN_OR_EQUAL,
            MetadataFilterOperator.BETWEEN,
            MetadataFilterOperator.IS_NULL,
            MetadataFilterOperator.IS_NOT_NULL,
        ),
    ),
    MetadataFieldType.LIST: MetadataFieldTypeSpec(
        value_column=METADATA_VALUE_TEXT_COLUMN,
        supports_full_text=False,
        supported_filter_operators=(
            MetadataFilterOperator.EQUALS,
            MetadataFilterOperator.NOT_EQUALS,
            MetadataFilterOperator.IS_NULL,
            MetadataFilterOperator.IS_NOT_NULL,
        ),
    ),
}


def get_value_column_for_type(field_type: MetadataFieldType) -> str:
    return METADATA_FIELD_TYPE_SPECS[field_type].value_column


def supports_full_text_search(field_type: MetadataFieldType) -> bool:
    return METADATA_FIELD_TYPE_SPECS[field_type].supports_full_text


def get_supported_filter_operators(field_type: MetadataFieldType) -> tuple[MetadataFilterOperator, ...]:
    return METADATA_FIELD_TYPE_SPECS[field_type].supported_filter_operators