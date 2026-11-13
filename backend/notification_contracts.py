from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class NotificationEventType(str, Enum):
    ITEM_QUANTITY_CHANGED = "item_quantity_changed"
    ITEM_UPDATED = "item_updated"
    INVENTORY_UPDATED = "inventory_updated"
    FILTER_TRIGGER_MATCHED = "filter_trigger_matched"


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
    item_id: int | None = Field(default=None, gt=0)
    changed_fields: list[str] = Field(min_length=1)
    details: dict[str, str | int | None] = Field(default_factory=dict)
    operation: Literal["created", "deleted"] | None = None
    quantity: int | None = None

    @model_validator(mode="after")
    def validate_creation_quantity(self) -> "ItemUpdatedData":
        if self.operation == "created" and self.quantity is None:
            raise ValueError("La quantità iniziale è obbligatoria")
        if self.operation != "created" and self.quantity is not None:
            raise ValueError("La quantità iniziale richiede un evento di creazione")
        if self.operation == "deleted":
            if self.item_id is not None or not isinstance(self.details.get("name"), str):
                raise ValueError("La cancellazione richiede il nome e non deve riferirsi all'ID dell'elemento")
        elif self.item_id is None:
            raise ValueError("L'ID dell'elemento è obbligatorio")
        return self


class InventoryUpdatedData(EventData):
    event_type: Literal["inventory_updated"] = "inventory_updated"
    changed_fields: list[str] = Field(min_length=1)
    details: dict[str, str | int | None] = Field(default_factory=dict)


class FilterTriggerMatchedData(EventData):
    event_type: Literal["filter_trigger_matched"] = "filter_trigger_matched"
    filter_id: int = Field(gt=0)
    trigger_id: int = Field(gt=0)
    filter_name: str
    count: int = Field(gt=0)
    scheduled_at: str
    trigger_revision: int = Field(gt=0)
    filter_fingerprint: str


NotificationEventData = Annotated[
    ItemQuantityChangedData | ItemUpdatedData | InventoryUpdatedData | FilterTriggerMatchedData,
    Field(discriminator="event_type"),
]
notification_event_adapter = TypeAdapter(NotificationEventData)


class NotificationPreferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    in_app_enabled: bool = False
    push_enabled: bool = False

    @model_validator(mode="after")
    def require_inbox_for_push(self) -> "NotificationPreferenceInput":
        if self.push_enabled and not self.in_app_enabled:
            raise ValueError("Le notifiche Push richiedono anche Inbox")
        return self


class NotificationBulkAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["read", "delete"]
    ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list)
    all: bool = False

    @model_validator(mode="after")
    def require_scope(self) -> "NotificationBulkAction":
        if self.all == bool(self.ids):
            raise ValueError("Specificare gli ID oppure tutte le notifiche")
        return self
