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


class NotificationRecipient(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["owner", "participants", "user", "group", "event_recipient"]
    id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_identity(self) -> "NotificationRecipient":
        if (self.kind in ("user", "group")) != (self.id is not None):
            raise ValueError("ID richiesto solo per utente o gruppo")
        return self


class NotificationRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_type: Literal["inventory_shared", "item_quantity_changed", "checklist_completed"]
    threshold: int | None = Field(default=None, ge=0, le=2147483647)
    recipients: list[NotificationRecipient] = Field(min_length=1, max_length=50)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_rule(self) -> "NotificationRuleInput":
        if (self.event_type == "item_quantity_changed") != (self.threshold is not None):
            raise ValueError("Soglia richiesta solo per variazioni di quantita")
        if self.event_type != "inventory_shared" and any(
            recipient.kind == "event_recipient" for recipient in self.recipients
        ):
            raise ValueError("Destinatario evento disponibile solo per condivisioni")
        return self


class NotificationPreferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    in_app_enabled: bool = True
    include_own_actions: bool = False
