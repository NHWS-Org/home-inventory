from datetime import datetime
from typing import Any, cast
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Date,
    ForeignKey,
    Table,
    Boolean,
    Numeric,
    Text,
    func,
    UniqueConstraint,
    CheckConstraint,
)
try:
    from sqlalchemy.dialects.postgresql import JSON
except ImportError:
    from sqlalchemy import JSON
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship, sessionmaker, declarative_base, Session
from enum import Enum

Base = declarative_base()

################################################
class LoggingData:
    data_ins = Column(DateTime, server_default=func.now(), nullable=False)
    data_mod = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    @declared_attr
    def user_ins(cls):
        return Column(Integer, ForeignKey('users.id'), nullable=True)

    @declared_attr
    def user_mod(cls):
        return Column(Integer, ForeignKey('users.id'), nullable=True)

    @declared_attr
    def user_ins_rel(cls):
        return relationship("User", foreign_keys=cast(Any, [cls.user_ins]))

    @declared_attr
    def user_mod_rel(cls):
        return relationship("User", foreign_keys=cast(Any, [cls.user_mod]))

################################################
class RoleEnum(str, Enum):
    admin = "admin"
    moderator = "moderator"
    viewer = "viewer"

################################################
# Definizione dei ruoli
class Role(Base, LoggingData):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

    users = relationship("User", back_populates="role", foreign_keys="[User.role_id]")

################################################
# Associazione tra utenti e gruppi
class UserGroupAssociation(Base, LoggingData):
    __tablename__ = "user_group_association"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), primary_key=True)

    # Relazioni esplicite con Foreign Keys
    user = relationship("User", back_populates="group_associations", foreign_keys=[user_id], overlaps="groups")
    group = relationship("Group", back_populates="user_associations", foreign_keys=[group_id], overlaps="users")

################################################
class User(Base, LoggingData):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    is_blocked = Column(Boolean, default=False)
    email = Column(String, nullable=True)

    # Relazioni esplicite
    role = relationship("Role", foreign_keys=[role_id])
    
    # Relazione con UserGroupAssociation con chiave esplicita
    group_associations = relationship("UserGroupAssociation",
                                      back_populates="user",
                                      foreign_keys="[UserGroupAssociation.user_id]",
                                      overlaps="groups"
                                    )
    # Relazione Many-to-Many con Group tramite user_group_association con Foreign Keys esplicite
    groups = relationship("Group",
                          secondary="user_group_association",
                          primaryjoin="User.id == UserGroupAssociation.user_id",
                          secondaryjoin="Group.id == UserGroupAssociation.group_id",
                          back_populates="users",
                          overlaps="group_associations,user,group"
                        )

################################################
class Group(Base, LoggingData):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    role_id = Column(Integer, ForeignKey("roles.id"))

    role = relationship("Role")

    # Relazione esplicita con UserGroupAssociation
    user_associations = relationship("UserGroupAssociation",
                                     back_populates="group",
                                     foreign_keys="[UserGroupAssociation.group_id]",
                                     overlaps="users,groups"
                                    )
    # Relazione Many-to-Many con User con chiavi esplicite
    users = relationship("User",
                         secondary="user_group_association",
                         primaryjoin="Group.id == UserGroupAssociation.group_id",
                         secondaryjoin="User.id == UserGroupAssociation.user_id",
                         back_populates="groups",
                         overlaps="user_associations,group,group_associations,user"
                        )

################################################
class Inventory(Base, LoggingData):
    __tablename__ = "inventories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    type = Column(String, nullable=False, default="INVENTORY")
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", foreign_keys=[owner_id])
    items = relationship("Item", back_populates="inventory", cascade="all, delete-orphan")

    # Relazione per gli utenti con cui è condiviso
    shared_with_users = relationship("SharedInventory", back_populates="inventory", cascade="all, delete-orphan")

    # Relazione per i gruppi con cui è condiviso
    shared_with_groups = relationship("SharedInventoryGroup", back_populates="inventory", cascade="all, delete-orphan")

################################################
class Item(Base, LoggingData):
    __tablename__ = "items"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    description = Column(String, nullable=True)
    quantity = Column(Integer, index=True)
    inventory_id = Column(Integer, ForeignKey("inventories.id"), nullable=False)
    inventory = relationship("Inventory", back_populates="items")
    metadata_values = relationship("ItemMetadataValue", back_populates="item", cascade="all, delete-orphan")
    barcodes = relationship("ItemBarcode", back_populates="item", cascade="all, delete-orphan", order_by="ItemBarcode.id")
    # Come riga di lista: assegnazione verso un item di inventario (max una)
    list_assignment = relationship(
        "ListAssignment", foreign_keys="ListAssignment.list_item_id", back_populates="list_item",
        cascade="all, delete-orphan", uselist=False,
    )
    # Come item di inventario: assegnazioni che lo prelevano da liste
    source_assignments = relationship(
        "ListAssignment", foreign_keys="ListAssignment.source_item_id", back_populates="source_item",
        cascade="all, delete-orphan",
    )

################################################
# Assegnazione: collega una riga di lista a un item di inventario da cui prelevare
class ListAssignment(Base, LoggingData):
    __tablename__ = "list_assignments"
    __table_args__ = (
        CheckConstraint("qty >= 1", name="ck_list_assignments_qty_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    list_item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, unique=True)
    source_item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    qty = Column(Integer, nullable=False, default=1)
    # Ultimo scarico effettuato alla spunta (serve per l'annullamento entro la finestra)
    applied_at = Column(DateTime, nullable=True)
    applied_qty = Column(Integer, nullable=True)

    list_item = relationship("Item", foreign_keys=[list_item_id], back_populates="list_assignment")
    source_item = relationship("Item", foreign_keys=[source_item_id], back_populates="source_assignments")

################################################
# Codici a barre / QR associati a un item (N per item)
class ItemBarcode(Base, LoggingData):
    __tablename__ = "item_barcodes"
    __table_args__ = (
        UniqueConstraint("item_id", "code", name="uq_item_barcodes_item_code"),
    )

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String, nullable=False, index=True)
    format = Column(String, nullable=True)  # es. ean_13, qr_code, code_128

    item = relationship("Item", back_populates="barcodes")

################################################
# Cache anagrafica prodotti da fonte esterna (Open * Facts)
class BarcodeProductCache(Base):
    __tablename__ = "barcode_product_cache"

    code = Column(String, primary_key=True)
    found = Column(Boolean, nullable=False, default=False)
    name = Column(String, nullable=True)
    brand = Column(String, nullable=True)
    quantity_label = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    source = Column(String, nullable=True)
    fetched_at = Column(DateTime, nullable=False)

################################################
class MetadataDefinition(Base, LoggingData):
    __tablename__ = "metadata_definitions"
    __table_args__ = (
        CheckConstraint("field_type IN ('TEXT', 'NUMBER', 'BOOLEAN', 'DATE', 'LIST')", name="ck_metadata_definitions_field_type"),
        UniqueConstraint("key", name="uq_metadata_definitions_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), nullable=False)
    label = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    field_type = Column(String(16), nullable=False)
    list_options = Column(JSON, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_required = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)

    assignments = relationship("MetadataDefinitionAssignment", back_populates="definition", cascade="all, delete-orphan")
    item_values = relationship("ItemMetadataValue", back_populates="definition", cascade="all, delete-orphan")


################################################
class MetadataDefinitionAssignment(Base, LoggingData):
    """Associazione tra una definizione metadato e il suo scope di applicazione."""
    __tablename__ = "metadata_definition_assignments"
    __table_args__ = (
        CheckConstraint("scope IN ('GLOBAL', 'INVENTORY_TYPE', 'INVENTORY')", name="ck_mda_scope"),
        CheckConstraint(
            "inventory_type IS NULL OR inventory_type IN ('INVENTORY', 'CHECKLIST')",
            name="ck_mda_inventory_type",
        ),
        CheckConstraint(
            "(scope = 'GLOBAL' AND inventory_id IS NULL AND inventory_type IS NULL) OR "
            "(scope = 'INVENTORY_TYPE' AND inventory_id IS NULL AND inventory_type IS NOT NULL) OR "
            "(scope = 'INVENTORY' AND inventory_id IS NOT NULL)",
            name="ck_mda_scope_target",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    definition_id = Column(Integer, ForeignKey("metadata_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    scope = Column(String(32), nullable=False)
    inventory_type = Column(String(16), nullable=True, index=True)
    inventory_id = Column(Integer, ForeignKey("inventories.id", ondelete="CASCADE"), nullable=True, index=True)

    definition = relationship("MetadataDefinition", back_populates="assignments")
    inventory = relationship("Inventory")

################################################
class ItemMetadataValue(Base, LoggingData):
    __tablename__ = "item_metadata_values"
    __table_args__ = (
        UniqueConstraint("item_id", "definition_id", name="uq_item_metadata_values_item_definition"),
        CheckConstraint(
            "(" 
            "CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_number IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_boolean IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_date IS NOT NULL THEN 1 ELSE 0 END"
            ") = 1",
            name="ck_item_metadata_values_single_typed_value",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    definition_id = Column(Integer, ForeignKey("metadata_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    value_text = Column(Text, nullable=True)
    value_number = Column(Numeric(14, 4), nullable=True)
    value_boolean = Column(Boolean, nullable=True)
    value_date = Column(Date, nullable=True)

    item = relationship("Item", back_populates="metadata_values")
    definition = relationship("MetadataDefinition", back_populates="item_values")

################################################
class SharedInventory(Base, LoggingData):
    __tablename__ = "shared_inventories"
    __table_args__ = (UniqueConstraint('user_id', 'inventory_id', name='_user_inventory_uc'),)

    id = Column(Integer, primary_key=True, index=True)
    inventory_id = Column(Integer, ForeignKey("inventories.id"))
    user_id = Column(Integer, ForeignKey("users.id"))

    inventory = relationship("Inventory", back_populates="shared_with_users")

################################################
class SharedInventoryGroup(Base, LoggingData):
    __tablename__ = "shared_inventory_groups"
    __table_args__ = (UniqueConstraint('group_id', 'inventory_id', name='_group_inventory_uc'),)

    id = Column(Integer, primary_key=True, index=True)
    inventory_id = Column(Integer, ForeignKey("inventories.id"))
    group_id = Column(Integer, ForeignKey("groups.id"))

    inventory = relationship("Inventory", back_populates="shared_with_groups")
    group = relationship("Group", backref="shared_inventories")

################################################
class Setting(Base, LoggingData):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(String)
    protected = Column(Boolean, default=False)  # ← nuovo campo

################################################
# Shadow table: versioni storiche degli item
class ItemVersion(Base):
    __tablename__ = "item_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, nullable=False, index=True)       # no FK → sopravvive alla delete
    inventory_id = Column(Integer, nullable=False, index=True)  # snapshot del contesto
    # snapshot del record al momento dell'azione
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    quantity = Column(Integer, nullable=True)
    # metadati versione
    version_num = Column(Integer, nullable=False)
    operation = Column(String(16), nullable=False)               # CREATE | UPDATE | DELETE
    changed_at = Column(DateTime, server_default=func.now(), nullable=False)
    changed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_by_username = Column(String, nullable=True)
    diff = Column(String, nullable=True)                         # JSON: {"field": {"from": v, "to": v}}

    changed_by = relationship("User", foreign_keys=[changed_by_id])

################################################
# Shadow table: versioni storiche degli inventari/liste
class InventoryVersion(Base):
    __tablename__ = "inventory_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inventory_id = Column(Integer, nullable=False, index=True)   # no FK → sopravvive alla delete
    # snapshot
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    owner_id = Column(Integer, nullable=True)
    owner_username = Column(String, nullable=True)
    # metadati versione
    version_num = Column(Integer, nullable=False)
    operation = Column(String(16), nullable=False)               # CREATE | UPDATE | DELETE
    changed_at = Column(DateTime, server_default=func.now(), nullable=False)
    changed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_by_username = Column(String, nullable=True)
    diff = Column(String, nullable=True)                         # JSON

    changed_by = relationship("User", foreign_keys=[changed_by_id])

################################################
# Template filtri salvati per inventari
class FilterTemplate(Base, LoggingData):
    __tablename__ = "filter_templates"
    __table_args__ = (
    )

    id = Column(Integer, primary_key=True, index=True)
    inventory_id = Column(Integer, nullable=True, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    filter_type = Column(String(32), nullable=False)  # "numeric", "date", "text", "composite"
    criteria = Column(JSON, nullable=False)  # JSON: {"filter_type": ..., "criteria": [...], "match_mode": "all"|"any"}
    is_shared = Column(Boolean, nullable=False, default=False)