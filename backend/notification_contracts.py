from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class NotificationEventType(str, Enum):
    ITEM_QUANTITY_CHANGED = "item_quantity_changed"
    ITEM_UPDATED = "item_updated"
    INVENTORY_UPDATED = "inventory_updated"


class EventData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    inventory_id: int = Field(gt=0)


class ItemQuantityChangedData(EventData):
    event_type: Literal["item_quantity_changed"] = "item_quantity_changed"
    item_id: int = Field(gt=0)
    previous_quantity: int
    quantity: int
    action_at: str | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ItemQuantityChangedData":
        if self.previous_quantity == self.quantity:
            raise ValueError("La quantita deve cambiare per generare un evento")
        return self


class ItemUpdatedData(EventData):
    event_type: Literal["item_updated"] = "item_updated"
    item_id: int = Field(gt=0)
    changed_fields: list[str] = Field(min_length=1)
    details: dict[str, str | int | None] = Field(default_factory=dict)


class InventoryUpdatedData(EventData):
    event_type: Literal["inventory_updated"] = "inventory_updated"
    changed_fields: list[str] = Field(min_length=1)
    details: dict[str, str | int | None] = Field(default_factory=dict)


NotificationEventData = Annotated[
    ItemQuantityChangedData | ItemUpdatedData | InventoryUpdatedData,
    Field(discriminator="event_type"),
]
notification_event_adapter = TypeAdapter(NotificationEventData)


class NotificationPreferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    in_app_enabled: bool = True
    push_enabled: bool = False
    include_own_actions: bool = False
