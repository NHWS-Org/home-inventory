import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, date
from decimal import Decimal

from main import app
from database import Base
from dependencies import get_db
from models import User, Role, Inventory, MetadataDefinition, ItemMetadataValue, Item, FilterTemplate


# Setup database per i test
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture
def db_session():
    """Fixture per sessione DB isolata per ogni test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def auth_user(db_session):
    """Fixture per utente autenticato di test."""
    role = Role(name="admin")
    db_session.add(role)
    db_session.commit()
    
    user = User(
        username="testuser",
        hashed_password="hashed123",
        role_id=role.id,
        email="test@example.com",
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def test_inventory(db_session, auth_user):
    """Fixture per inventario di test."""
    inventory = Inventory(
        name="Test Inventory",
        type="INVENTORY",
        owner_id=auth_user.id,
        user_ins=auth_user.id,
        user_mod=auth_user.id,
    )
    db_session.add(inventory)
    db_session.commit()
    return inventory


class TestMetadataDefinitions:
    """Test per API definizioni metadati."""

    def test_create_metadata_definition(self, db_session, auth_user, test_inventory):
        """Test creazione definizione metadato (chiave globale, scope via assignment)."""
        payload = {
            "key": "test_number",
            "label": "Test Number",
            "description": "A test number field",
            "field_type": "NUMBER",
            "sort_order": 1,
            "is_required": False,
            "is_active": True,
        }
        # Nota: questo test richiederebbe autenticazione nel vero endpoint
        # Per ora è un test strutturale
        definition = MetadataDefinition(**payload, user_ins=auth_user.id, user_mod=auth_user.id)
        db_session.add(definition)
        db_session.commit()

        assert definition.id is not None
        assert definition.key == "test_number"
        assert definition.field_type == "NUMBER"

    def test_metadata_definition_unique_constraint(self, db_session, auth_user, test_inventory):
        """Test constraint univocità globale sulla chiave (uq_metadata_definitions_key)."""
        def_1 = MetadataDefinition(
            key="unique_key",
            label="First",
            field_type="TEXT",
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(def_1)
        db_session.commit()

        def_2 = MetadataDefinition(
            key="unique_key",  # Stessa chiave
            label="Duplicate",
            field_type="TEXT",
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(def_2)
        
        with pytest.raises(Exception):  # IntegrityError dovrebbe sollevarsi
            db_session.commit()


class TestItemMetadataValues:
    """Test per API valori metadati."""

    def test_create_numeric_metadata_value(self, db_session, auth_user, test_inventory):
        """Test creazione valore metadato numerico."""
        definition = MetadataDefinition(
            key="price",
            label="Prezzo",
            field_type="NUMBER",
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(definition)
        db_session.commit()

        item = Item(
            name="Product A",
            inventory_id=test_inventory.id,
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(item)
        db_session.commit()

        value = ItemMetadataValue(
            item_id=item.id,
            definition_id=definition.id,
            value_number=Decimal("99.99"),
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(value)
        db_session.commit()

        assert value.id is not None
        assert value.value_number == Decimal("99.99")
        assert value.value_text is None

    def test_metadata_single_typed_value_constraint(self, db_session, auth_user, test_inventory):
        """Test constraint: solo UN valore typed deve essere settato."""
        definition = MetadataDefinition(
            key="mixed",
            label="Mixed",
            field_type="NUMBER",
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(definition)
        
        item = Item(
            name="Product B",
            inventory_id=test_inventory.id,
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(item)
        db_session.commit()

        # Tentativo di settare sia value_number che value_text
        value = ItemMetadataValue(
            item_id=item.id,
            definition_id=definition.id,
            value_number=Decimal("100.00"),
            value_text="also text",
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(value)
        
        with pytest.raises(Exception):  # IntegrityError dovrebbe sollevarsi
            db_session.commit()


class TestFilterTemplates:
    """Test per API template filtri."""

    def test_create_filter_template(self, db_session, auth_user, test_inventory):
        """Test creazione template filtro."""
        criteria_payload = {
            "filter_type": "numeric",
            "criteria": [
                {
                    "definition_id": 1,
                    "operator": "gte",
                    "value_number": 100,
                }
            ],
            "match_mode": "all",
        }
        
        template = FilterTemplate(
            inventory_id=test_inventory.id,
            name="High Price Items",
            description="Items with price >= 100",
            filter_type="numeric",
            criteria=criteria_payload,
            is_shared=False,
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(template)
        db_session.commit()

        assert template.id is not None
        assert template.name == "High Price Items"
        assert template.filter_type == "numeric"
        assert template.criteria["match_mode"] == "all"

    def test_filter_template_name_uniqueness(self, db_session, auth_user, test_inventory):
        """L'univocità del nome per utente è applicativa (route), non un vincolo DB:
        a livello di modello due template con lo stesso nome per lo stesso utente possono coesistere."""
        criteria = {"filter_type": "numeric", "criteria": [], "match_mode": "all"}

        template_1 = FilterTemplate(
            inventory_id=test_inventory.id,
            name="Template A",
            filter_type="numeric",
            criteria=criteria,
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(template_1)
        db_session.commit()

        template_2 = FilterTemplate(
            inventory_id=test_inventory.id,
            name="Template A",  # Stesso nome: nessun vincolo DB lo impedisce
            filter_type="date",
            criteria=criteria,
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(template_2)
        db_session.commit()

        assert template_1.id != template_2.id


class TestMetadataValidation:
    """Test per validazione logic metadata."""

    def test_metadata_definition_field_type_check_constraint(self, db_session, auth_user, test_inventory):
        """Test check constraint su field_type."""
        # Valid field types dovrebbero funzionare
        for field_type in ["TEXT", "NUMBER", "BOOLEAN", "DATE"]:
            definition = MetadataDefinition(
                key=f"valid_{field_type.lower()}",
                label=f"Valid {field_type}",
                field_type=field_type,
                user_ins=auth_user.id,
                user_mod=auth_user.id,
            )
            db_session.add(definition)
        
        db_session.commit()
        
        # Invalid field type dovrebbe fallare
        invalid_definition = MetadataDefinition(
            key="invalid",
            label="Invalid",
            field_type="INVALID_TYPE",  # Non supportato
            user_ins=auth_user.id,
            user_mod=auth_user.id,
        )
        db_session.add(invalid_definition)
        
        with pytest.raises(Exception):  # IntegrityError per check constraint
            db_session.commit()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
