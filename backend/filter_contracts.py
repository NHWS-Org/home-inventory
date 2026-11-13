from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

ContainerType = Literal["INVENTORY", "CHECKLIST"]


class RelativeDate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    relative_days: int = Field(ge=-36500, le=36500)


FilterValue = str | int | float | bool | RelativeDate | None


class FilterCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: Literal["item", "metadata"]
    field: str = Field(min_length=1, max_length=64)
    definition_id: int | None = Field(default=None, gt=0)
    operator: Literal[
        "equals", "not_equals", "contains", "not_contains", "gt", "gte",
        "lt", "lte", "between", "is_null", "is_not_null",
    ]
    value: FilterValue = None
    range_from: FilterValue = None
    range_to: FilterValue = None


class FilterInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    is_shared: bool = False
    container_type: ContainerType | None = None
    match_mode: Literal["all", "any"] = "all"
    conditions: list[FilterCondition] = Field(min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Nome obbligatorio")
        return value


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Timezone IANA non valida") from None
    return value


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    inventory_id: int | None = Field(default=None, gt=0)
    timezone: str = "Europe/Rome"

    _timezone = field_validator("timezone")(validate_timezone)


class FilterPreviewInput(FilterInput, EvaluationInput):
    pass


class TriggerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=128)
    filter_id: int = Field(gt=0)
    enabled: bool = True
    time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Europe/Rome"
    weekdays: list[Annotated[int, Field(strict=True, ge=1, le=7)]] = Field(min_length=1, max_length=7)
    inventory_ids: list[Annotated[int, Field(strict=True, gt=0)]] | None = None
    notify_mode: Literal["always", "changed"] = "always"

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Nome obbligatorio")
        return value

    _timezone = field_validator("timezone")(validate_timezone)

    @field_validator("weekdays", "inventory_ids")
    @classmethod
    def unique_ids(cls, value):
        if value is not None:
            if not value or len(value) != len(set(value)) or len(value) > 100:
                raise ValueError("Elenco non vuoto, senza duplicati, massimo 100 valori")
            return sorted(value)
        return value


class SubscriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class ScopeInventory(BaseModel):
    id: int
    name: str
    type: ContainerType


class ScopePreview(BaseModel):
    scope_type: str
    summary: str
    inventories: list[ScopeInventory]


class FilterResponse(BaseModel):
    name: str
    description: str | None
    is_shared: bool
    container_type: ContainerType | None
    match_mode: Literal["all", "any"]
    conditions: list[FilterCondition] = Field(max_length=50)
    id: int
    user_ins: int | None
    user_mod: int | None
    username_ins: str | None = None
    username_mod: str | None = None
    data_ins: datetime
    data_mod: datetime
    scope_preview: ScopePreview
    trigger_count: int
    can_manage: bool
    validation_error: str | None = None


class EvaluationContainer(ScopeInventory):
    item_ids: list[int]
    count: int


class EvaluationResponse(BaseModel):
    containers: list[EvaluationContainer]
    total_count: int


class FilterField(BaseModel):
    field: str
    label: str
    source: Literal["item", "metadata"]
    field_type: Literal["TEXT", "NUMBER", "BOOLEAN", "DATE", "LIST"]
    definition_id: int | None = None
    operators: list[str]
    container_types: list[ContainerType]
    list_options: list[dict[str, str]] | None = None


class TriggerResponse(TriggerInput):
    id: int
    user_ins: int | None = None
    user_mod: int | None = None
    username_ins: str | None = None
    username_mod: str | None = None
    data_ins: datetime | None = None
    data_mod: datetime | None = None
    filter_name: str
    scope_preview: ScopePreview
    can_manage: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_result_count: int | None
    last_container_count: int | None
    last_error: str | None
