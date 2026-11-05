from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class NotificationEventType(str, Enum):
    INVENTORY_SHARED = "inventory_shared"
    ITEM_QUANTITY_CHANGED = "item_quantity_changed"
    CHECKLIST_COMPLETED = "checklist_completed"


class EventData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    inventory_id: int = Field(gt=0)


class InventorySharedData(EventData):
    event_type: Literal["inventory_shared"] = "inventory_shared"
    recipient_kind: Literal["user", "group"]
    recipient_id: int = Field(gt=0)


class ItemQuantityChangedData(EventData):
    event_type: Literal["item_quantity_changed"] = "item_quantity_changed"
    item_id: int = Field(gt=0)
    previous_quantity: int
    quantity: int

    @model_validator(mode="after")
    def require_change(self) -> "ItemQuantityChangedData":
        if self.previous_quantity == self.quantity:
            raise ValueError("La quantita deve cambiare per generare un evento")
        return self


class ChecklistCompletedData(EventData):
    event_type: Literal["checklist_completed"] = "checklist_completed"


NotificationEventData = Annotated[
    InventorySharedData | ItemQuantityChangedData | ChecklistCompletedData,
    Field(discriminator="event_type"),
]
notification_event_adapter = TypeAdapter(NotificationEventData)
