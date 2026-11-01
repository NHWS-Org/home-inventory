from __future__ import annotations
from typing import List, Literal, Optional, TYPE_CHECKING
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime, date
from metadata_model import (
    InventoryContainerType,
    MetadataDefinitionScope,
    MetadataFieldType,
    MetadataFilterOperator,
)

################################################
# Modello base per aggiungere campi comuni
class LoggingResponse(BaseModel):
    data_ins: datetime
    data_mod: datetime
    user_ins: Optional[int] = None  # ID dell'utente che ha creato il record
    user_mod: Optional[int] = None  # ID dell'utente che ha modificato il record

LoggingResponse.model_rebuild()

################################################
# Modello per i ruoli
class RoleBase(BaseModel):
    name: str

class RoleCreate(RoleBase):
    pass

class RoleResponse(RoleBase, LoggingResponse):
    id: int
    
    class Config:
        from_attributes = True

RoleBase.model_rebuild()
RoleCreate.model_rebuild()
RoleResponse.model_rebuild()

################################################
# Modello per gli utenti
class UserBase(BaseModel):
    username: str
    email: Optional[str] = None  # ✅ Aggiunto campo email

class UserCreate(UserBase):
    password: str  # La password non viene restituita nelle risposte
    role_id: int

class UserCreateSelf(UserBase):
    password: str  # La password non viene restituita nelle risposte

class UserUpdate(UserBase):
    password: Optional[str] = None
    is_blocked: Optional[bool] = None  # ✅ Permette di aggiornare lo stato bloccato
    role_id: int

class UserSelfUpdate(BaseModel): # Usato per aggiornare i dati dell'utente loggato, anche se non admin
    email: Optional[str] = None
    password: Optional[str] = None

class UserResponse(UserBase, LoggingResponse):
    id: int
    role: 'RoleResponse'
    is_blocked: bool
    
    class Config:
        from_attributes = True

UserBase.model_rebuild()
UserCreate.model_rebuild()
UserCreateSelf.model_rebuild()
UserUpdate.model_rebuild()
UserSelfUpdate.model_rebuild()
UserResponse.model_rebuild()

################################################
# Modello per i gruppi
class GroupBase(BaseModel):
    name: str

class GroupCreate(GroupBase):
    role_id: int

class GroupResponse(GroupBase, LoggingResponse):
    id: int
    users: List['UserResponse'] = []
    role: 'RoleResponse'

    class Config:
        from_attributes = True

GroupBase.model_rebuild()
GroupCreate.model_rebuild()
GroupResponse.model_rebuild()

################################################
# Modello per la creazione e risposta di un inventario
class InventoryBase(BaseModel):
    name: str

class InventoryCreate(InventoryBase):
    pass 

class InventoryUpdate(InventoryBase):
    pass

class InventoryResponse(InventoryBase, LoggingResponse):
    id: int
    owner: 'UserResponse'  # Riferimento all'utente proprietario
    version_num: int = 0
    
    class Config:
        from_attributes = True

class InventoryResponseWithItemCount(InventoryResponse):
    item_count: int

InventoryBase.model_rebuild()
InventoryCreate.model_rebuild()
InventoryUpdate.model_rebuild()
InventoryResponse.model_rebuild()
InventoryResponseWithItemCount.model_rebuild()

################################################
# Modello per gli elementi di un inventario
class ItemBase(BaseModel):
    name: str
    description: Optional[str] = None
    quantity: int
    inventory_id: int

class ItemCreate(ItemBase):
    barcodes: List['ItemBarcodeCreate'] = []

class ItemUpdate(BaseModel):
    name: Optional[str]
    description: Optional[str]
    quantity: Optional[int]
    inventory_id: Optional[int]

class ItemDelete(BaseModel):
    confirm: bool

class ItemBarcodeResponse(BaseModel):
    id: int
    code: str
    format: Optional[str] = None

    class Config:
        from_attributes = True

class ItemBarcodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    format: Optional[str] = Field(default=None, max_length=32)

class BarcodeMatch(BaseModel):
    item_id: int
    name: str
    quantity: Optional[int] = None
    inventory_id: int
    inventory_name: Optional[str] = None
    inventory_type: Optional[str] = None

class BarcodeProduct(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    quantity_label: Optional[str] = None
    image_url: Optional[str] = None
    source: Optional[str] = None

class BarcodeLookupResponse(BaseModel):
    code: str
    matches: List[BarcodeMatch] = []
    product: Optional[BarcodeProduct] = None

class AssignmentCreate(BaseModel):
    list_item_id: int
    source_item_id: int
    qty: int = Field(default=1, ge=1)

class AssignmentUpdate(BaseModel):
    qty: int = Field(ge=1)

class AssignmentResponse(BaseModel):
    id: int
    list_item_id: int
    list_item_name: Optional[str] = None
    list_id: Optional[int] = None
    list_name: Optional[str] = None
    list_checked: bool = False
    source_item_id: int
    source_name: Optional[str] = None
    source_inventory_id: Optional[int] = None
    source_inventory_name: Optional[str] = None
    source_stock: Optional[int] = None
    source_net_qty: Optional[int] = None
    qty: int

class ItemAssignmentSummary(BaseModel):
    """Presente sulle righe di lista collegate a un item di inventario."""
    id: int
    list_checked: bool = False
    source_item_id: int
    source_name: Optional[str] = None
    source_inventory_id: Optional[int] = None
    source_inventory_name: Optional[str] = None
    source_stock: Optional[int] = None
    source_net_qty: Optional[int] = None
    qty: int

class ItemResponse(ItemBase, LoggingResponse):
    id: int
    barcodes: List[ItemBarcodeResponse] = []
    assignment: Optional[ItemAssignmentSummary] = None
    assignment_count: int = 0
    assigned_qty: int = 0
    net_qty: Optional[int] = None
    username_ins: Optional[str] = None
    username_mod: Optional[str] = None
    metadata_values: List['ItemMetadataValueResponse'] = []
    version_num: int = 0
    
    class Config:
        from_attributes = True

ItemBase.model_rebuild()
ItemCreate.model_rebuild()
ItemUpdate.model_rebuild()
ItemDelete.model_rebuild()

################################################
# Versioni storica degli item (shadow table)
class ItemVersionResponse(BaseModel):
    id: int
    item_id: int
    inventory_id: int
    inventory_name: Optional[str] = None
    inventory_type: Optional[str] = None
    name: str
    description: Optional[str] = None
    quantity: Optional[int] = None
    version_num: int
    operation: str
    changed_at: datetime
    changed_by_id: Optional[int] = None
    changed_by_username: Optional[str] = None
    diff: Optional[str] = None

    class Config:
        from_attributes = True

ItemVersionResponse.model_rebuild()

################################################
# Versione storica degli inventari/liste (shadow table)
class InventoryVersionResponse(BaseModel):
    id: int
    inventory_id: int
    name: str
    type: str
    owner_id: Optional[int] = None
    owner_username: Optional[str] = None
    version_num: int
    operation: str
    changed_at: datetime
    changed_by_id: Optional[int] = None
    changed_by_username: Optional[str] = None
    diff: Optional[str] = None

    class Config:
        from_attributes = True

InventoryVersionResponse.model_rebuild()

################################################
# Richiesta cancellazione massiva versioni
class VersionBulkDeleteRequest(BaseModel):
    version_nums: List[int]

VersionBulkDeleteRequest.model_rebuild()

##############################################################
# Modello per la gestione del token di accesso
class Token(BaseModel):
    access_token: str
    token_type: str

# Modello per i dati del token
class TokenData(BaseModel):
    username: Optional[str] = None

Token.model_rebuild()
TokenData.model_rebuild()

##############################################################
class InventoryShareRequest(BaseModel):
    group_ids: List[int]

InventoryShareRequest.model_rebuild()

##############################################################
# Impostazioni generali dell'applicazione
class AppSettingUpdate(BaseModel):
    key: str
    value: str
    protected: bool = False

class AppSettingResponse(BaseModel):
    key: str
    value: str
    protected: bool

AppSettingUpdate.model_rebuild()
AppSettingResponse.model_rebuild()

##############################################################
# Metadati EAV - Assegnazioni

class MetadataAssignmentCreate(BaseModel):
    scope: MetadataDefinitionScope
    inventory_type: Optional[InventoryContainerType] = None
    inventory_id: Optional[int] = None

    @model_validator(mode="after")
    def validate_assignment_target(self):
        if self.scope == MetadataDefinitionScope.GLOBAL:
            if self.inventory_type is not None or self.inventory_id is not None:
                raise ValueError("Per scope GLOBAL non specificare inventory_type o inventory_id")
        elif self.scope == MetadataDefinitionScope.INVENTORY_TYPE:
            if self.inventory_type is None:
                raise ValueError("Per scope INVENTORY_TYPE inventory_type è obbligatorio")
            if self.inventory_id is not None:
                raise ValueError("Per scope INVENTORY_TYPE inventory_id non deve essere specificato")
        elif self.scope == MetadataDefinitionScope.INVENTORY:
            if self.inventory_id is None:
                raise ValueError("Per scope INVENTORY inventory_id è obbligatorio")
        return self


class MetadataAssignmentResponse(BaseModel):
    id: int
    definition_id: int
    scope: MetadataDefinitionScope
    inventory_type: Optional[InventoryContainerType] = None
    inventory_id: Optional[int] = None
    data_ins: Optional[datetime] = None
    data_mod: Optional[datetime] = None

    class Config:
        from_attributes = True


##############################################################
# Metadati EAV - Definizioni

class MetadataListOption(BaseModel):
    value: str
    label: str

    @field_validator("value", "label")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Valore opzione non valido")
        return normalized


class MetadataDefinitionBase(BaseModel):
    key: str
    label: str
    description: Optional[str] = None
    field_type: MetadataFieldType
    list_options: List[MetadataListOption] = Field(default_factory=list)
    sort_order: int = 0
    is_required: bool = False
    is_active: bool = True

    @field_validator("list_options", mode="before")
    @classmethod
    def default_list_options(cls, value):
        return [] if value is None else value

    @model_validator(mode="after")
    def validate_list_metadata(self):
        if self.field_type == MetadataFieldType.LIST and not self.list_options:
            raise ValueError("Per il tipo LIST è obbligatoria almeno un'opzione")
        return self


class MetadataDefinitionCreate(MetadataDefinitionBase):
    pass


class MetadataDefinitionUpdate(BaseModel):
    key: Optional[str] = None
    label: Optional[str] = None
    description: Optional[str] = None
    list_options: Optional[List[MetadataListOption]] = None
    sort_order: Optional[int] = None
    is_required: Optional[bool] = None
    is_active: Optional[bool] = None


class MetadataDefinitionResponse(MetadataDefinitionBase, LoggingResponse):
    id: int
    assignments: List[MetadataAssignmentResponse] = []

    class Config:
        from_attributes = True


MetadataAssignmentCreate.model_rebuild()
MetadataAssignmentResponse.model_rebuild()
MetadataListOption.model_rebuild()
MetadataDefinitionBase.model_rebuild()
MetadataDefinitionCreate.model_rebuild()
MetadataDefinitionUpdate.model_rebuild()
MetadataDefinitionResponse.model_rebuild()


##############################################################
# Metadati EAV - Valori typed
class ItemMetadataTypedValue(BaseModel):
    value_text: Optional[str] = None
    value_number: Optional[Decimal] = None
    value_boolean: Optional[bool] = None
    value_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_single_typed_value(self):
        set_count = sum(
            value is not None
            for value in (
                self.value_text,
                self.value_number,
                self.value_boolean,
                self.value_date,
            )
        )
        if set_count != 1:
            raise ValueError("Esattamente un valore tra text/number/boolean/date deve essere valorizzato")
        return self


class ItemMetadataValueCreate(ItemMetadataTypedValue):
    item_id: int
    definition_id: int


class ItemMetadataValueUpdate(ItemMetadataTypedValue):
    pass


class ItemMetadataValueResponse(ItemMetadataTypedValue, LoggingResponse):
    id: int
    item_id: int
    definition_id: int
    definition_key: Optional[str] = None
    definition_label: Optional[str] = None
    field_type: Optional[MetadataFieldType] = None
    display_value: Optional[str] = None

    class Config:
        from_attributes = True


class ItemMetadataValueUpsert(ItemMetadataTypedValue):
    definition_id: int


class ItemMetadataBulkUpsertRequest(BaseModel):
    item_id: int
    values: List[ItemMetadataValueUpsert]


ItemMetadataTypedValue.model_rebuild()
ItemMetadataValueCreate.model_rebuild()
ItemMetadataValueUpdate.model_rebuild()
ItemMetadataValueResponse.model_rebuild()
ItemMetadataValueUpsert.model_rebuild()
ItemMetadataBulkUpsertRequest.model_rebuild()
ItemResponse.model_rebuild()


##############################################################
# Filtri testuali/lista avanzati su metadati
class TextMetadataFilterCriterion(BaseModel):
    definition_id: int
    operator: MetadataFilterOperator
    value_text: Optional[str] = None

    @field_validator("value_text", mode="before")
    @classmethod
    def normalize_value_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_text_operator_payload(self):
        value_operators = {
            MetadataFilterOperator.EQUALS,
            MetadataFilterOperator.NOT_EQUALS,
            MetadataFilterOperator.CONTAINS,
            MetadataFilterOperator.NOT_CONTAINS,
        }
        null_operators = {
            MetadataFilterOperator.IS_NULL,
            MetadataFilterOperator.IS_NOT_NULL,
        }

        if self.operator in value_operators:
            if self.value_text is None:
                raise ValueError("Per questo operatore è obbligatorio value_text")
            return self

        if self.operator in null_operators:
            return self

        raise ValueError("Operatore non supportato per filtri testuali")


class TextMetadataFilterRequest(BaseModel):
    inventory_id: int
    match_mode: Literal["all", "any"] = "all"
    criteria: List[TextMetadataFilterCriterion]

    @model_validator(mode="after")
    def validate_criteria(self):
        if not self.criteria:
            raise ValueError("Almeno un criterio testuale è obbligatorio")
        return self


class TextMetadataFilterResponse(BaseModel):
    inventory_id: int
    match_mode: Literal["all", "any"]
    item_ids: List[int]
    count: int


TextMetadataFilterCriterion.model_rebuild()
TextMetadataFilterRequest.model_rebuild()
TextMetadataFilterResponse.model_rebuild()


##############################################################
# Filtri numerici avanzati su metadati
class NumericMetadataFilterCriterion(BaseModel):
    definition_id: int
    operator: MetadataFilterOperator
    value_number: Optional[Decimal] = None
    range_from: Optional[Decimal] = None
    range_to: Optional[Decimal] = None

    @model_validator(mode="after")
    def validate_numeric_operator_payload(self):
        between_operator = MetadataFilterOperator.BETWEEN
        unary_operators = {
            MetadataFilterOperator.EQUALS,
            MetadataFilterOperator.NOT_EQUALS,
            MetadataFilterOperator.GREATER_THAN,
            MetadataFilterOperator.GREATER_THAN_OR_EQUAL,
            MetadataFilterOperator.LESS_THAN,
            MetadataFilterOperator.LESS_THAN_OR_EQUAL,
        }
        null_operators = {
            MetadataFilterOperator.IS_NULL,
            MetadataFilterOperator.IS_NOT_NULL,
        }

        if self.operator == between_operator:
            if self.range_from is None or self.range_to is None:
                raise ValueError("Per operator=between sono obbligatori range_from e range_to")
            if self.range_from > self.range_to:
                raise ValueError("range_from non può essere maggiore di range_to")
            return self

        if self.operator in unary_operators:
            if self.value_number is None:
                raise ValueError("Per questo operatore è obbligatorio value_number")
            return self

        if self.operator in null_operators:
            return self

        raise ValueError("Operatore non supportato per filtri numerici")


class NumericMetadataFilterRequest(BaseModel):
    inventory_id: int
    match_mode: Literal["all", "any"] = "all"
    criteria: List[NumericMetadataFilterCriterion]

    @model_validator(mode="after")
    def validate_criteria(self):
        if not self.criteria:
            raise ValueError("Almeno un criterio numerico è obbligatorio")
        return self


class NumericMetadataFilterResponse(BaseModel):
    inventory_id: int
    match_mode: Literal["all", "any"]
    item_ids: List[int]
    count: int


NumericMetadataFilterCriterion.model_rebuild()
NumericMetadataFilterRequest.model_rebuild()
NumericMetadataFilterResponse.model_rebuild()


##############################################################
# Filtri date avanzati su metadati
class DateMetadataFilterCriterion(BaseModel):
    definition_id: int
    operator: MetadataFilterOperator
    value_date: Optional[date] = None
    range_from: Optional[date] = None
    range_to: Optional[date] = None

    @field_validator("value_date", "range_from", "range_to", mode="before")
    @classmethod
    def parse_dynamic_date_tokens(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"today", "oggi"}:
                return date.today()
            if normalized == "":
                return None
        return value

    @model_validator(mode="after")
    def validate_date_operator_payload(self):
        between_operator = MetadataFilterOperator.BETWEEN
        unary_operators = {
            MetadataFilterOperator.EQUALS,
            MetadataFilterOperator.NOT_EQUALS,
            MetadataFilterOperator.GREATER_THAN,
            MetadataFilterOperator.GREATER_THAN_OR_EQUAL,
            MetadataFilterOperator.LESS_THAN,
            MetadataFilterOperator.LESS_THAN_OR_EQUAL,
        }
        null_operators = {
            MetadataFilterOperator.IS_NULL,
            MetadataFilterOperator.IS_NOT_NULL,
        }

        if self.operator == between_operator:
            if self.range_from is None or self.range_to is None:
                raise ValueError("Per operator=between sono obbligatori range_from e range_to")
            if self.range_from > self.range_to:
                raise ValueError("range_from non può essere maggiore di range_to")
            return self

        if self.operator in unary_operators:
            if self.value_date is None:
                raise ValueError("Per questo operatore è obbligatorio value_date")
            return self

        if self.operator in null_operators:
            return self

        raise ValueError("Operatore non supportato per filtri date")


class DateMetadataFilterRequest(BaseModel):
    inventory_id: int
    match_mode: Literal["all", "any"] = "all"
    criteria: List[DateMetadataFilterCriterion]

    @model_validator(mode="after")
    def validate_criteria(self):
        if not self.criteria:
            raise ValueError("Almeno un criterio date è obbligatorio")
        return self


class DateMetadataFilterResponse(BaseModel):
    inventory_id: int
    match_mode: Literal["all", "any"]
    item_ids: List[int]
    count: int


DateMetadataFilterCriterion.model_rebuild()
DateMetadataFilterRequest.model_rebuild()
DateMetadataFilterResponse.model_rebuild()


##############################################################
# Filtri boolean avanzati su metadati
class BooleanMetadataFilterCriterion(BaseModel):
    definition_id: int
    operator: MetadataFilterOperator
    value_boolean: Optional[bool] = None

    @model_validator(mode="after")
    def validate_boolean_operator_payload(self):
        binary_operators = {
            MetadataFilterOperator.EQUALS,
            MetadataFilterOperator.NOT_EQUALS,
        }
        unary_operators = {
            MetadataFilterOperator.IS_NULL,
            MetadataFilterOperator.IS_NOT_NULL,
        }

        if self.operator in binary_operators:
            if self.value_boolean is None:
                raise ValueError("Per questo operatore è obbligatorio value_boolean")
            return self

        if self.operator in unary_operators:
            return self

        raise ValueError("Operatore non supportato per filtri boolean")


class BooleanMetadataFilterRequest(BaseModel):
    inventory_id: int
    match_mode: Literal["all", "any"] = "all"
    criteria: List[BooleanMetadataFilterCriterion]

    @model_validator(mode="after")
    def validate_criteria(self):
        if not self.criteria:
            raise ValueError("Almeno un criterio boolean è obbligatorio")
        return self


class BooleanMetadataFilterResponse(BaseModel):
    inventory_id: int
    match_mode: Literal["all", "any"]
    item_ids: List[int]
    count: int


BooleanMetadataFilterCriterion.model_rebuild()
BooleanMetadataFilterRequest.model_rebuild()
BooleanMetadataFilterResponse.model_rebuild()


##############################################################
# Template filtri salvati
class FilterTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    filter_type: Literal["numeric", "date", "boolean", "text", "composite"]
    criteria: dict
    is_shared: bool = False


class FilterTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    filter_type: Optional[Literal["numeric", "date", "boolean", "text", "composite"]] = None
    criteria: Optional[dict] = None
    is_shared: Optional[bool] = None


class FilterTemplateResponse(FilterTemplateCreate, LoggingResponse):
    id: int
    inventory_id: Optional[int] = None

    class Config:
        from_attributes = True


class FilterTemplateListResponse(BaseModel):
    id: int
    inventory_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    filter_type: str
    criteria_count: Optional[int] = None
    is_shared: bool
    data_ins: datetime
    data_mod: datetime

    class Config:
        from_attributes = True


class FilterTemplateScopeInventory(BaseModel):
    id: int
    name: str
    type: str


class FilterTemplateScopePreview(BaseModel):
    scope_type: str  # "global" | "all_inventories" | "all_checklists" | "specific" | "none"
    summary: str
    inventories: List[FilterTemplateScopeInventory] = []


FilterTemplateCreate.model_rebuild()
FilterTemplateUpdate.model_rebuild()
FilterTemplateResponse.model_rebuild()
FilterTemplateListResponse.model_rebuild()
FilterTemplateScopeInventory.model_rebuild()
FilterTemplateScopePreview.model_rebuild()