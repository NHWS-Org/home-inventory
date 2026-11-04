"""Convert the application's pg_dump --column-inserts exports without executing SQL."""

import json
import re
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Integer, JSON, Numeric, String, Text, Time

from backup_archive import BACKUP_FORMAT, BACKUP_FORMAT_VERSION, encode_value, write_backup_archive
from models import Base


_TOKEN = re.compile(
    r"(?P<space>\s+|--[^\n]*(?:\n|$))"
    r"|(?P<meta>^\\(?:unrestrict|restrict)[ \t]+\w+[ \t]*(?:\n|$))"
    r"|(?P<escape>[eE]'(?:''|\\.|[^'\\])*')"
    r"|(?P<string>'(?:''|[^'])*')"
    r'|(?P<identifier>"(?:[^"]|"")*"|[A-Za-z_][A-Za-z_0-9$]*)'
    r"|(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<punct>[(),;.=])",
    re.MULTILINE,
)


def _statements(sql: str):
    offset = 0
    tokens: list[str] = []
    while offset < len(sql):
        match = _TOKEN.match(sql, offset)
        if match is None:
            raise ValueError(f"Sintassi SQL non supportata alla posizione {offset}")
        offset = match.end()
        if match.lastgroup in {"space", "meta"}:
            continue
        token = match.group()
        if token == ";":
            if tokens:
                yield tokens
                tokens = []
        else:
            tokens.append(token)
    if tokens:
        raise ValueError("Istruzione SQL incompleta: manca il punto e virgola")


def _identifier(token: str) -> str:
    if token.startswith('"'):
        return token[1:-1].replace('""', '"')
    if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9$]*", token):
        return token.lower()
    raise ValueError("Identificatore SQL non valido")


def _literal(token: str) -> Any:
    if token.upper() == "NULL":
        return None
    if token.upper() in {"TRUE", "FALSE"}:
        return token.upper() == "TRUE"
    if token.startswith("'"):
        return token[1:-1].replace("''", "'")
    if token[:2].upper() == "E'":
        raw = token[2:-1].replace("''", "'")
        escapes = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}

        def decode(match):
            value = match.group(1)
            if value.startswith(("u", "U")):
                return chr(int(value[1:], 16))
            if value.startswith("x"):
                return chr(int(value[1:], 16))
            if value[0] in "01234567":
                return chr(int(value, 8))
            return escapes.get(value, value)

        return re.sub(
            r"\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|x[0-9a-fA-F]{1,2}|[0-7]{1,3}|.)",
            decode,
            raw,
        )
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", token):
        return Decimal(token)
    raise ValueError("Espressione SQL non supportata: sono ammessi solo valori letterali")


def _typed_value(value: Any, column_type: Any) -> Any:
    if value is None:
        return None
    if isinstance(column_type, Boolean):
        if not isinstance(value, bool):
            raise ValueError("Valore booleano non valido")
    elif isinstance(column_type, Integer):
        if not isinstance(value, Decimal) or value != value.to_integral_value():
            raise ValueError("Valore intero non valido")
        value = int(value)
    elif isinstance(column_type, Numeric):
        value = Decimal(value)
    elif isinstance(column_type, DateTime):
        value = datetime.fromisoformat(value)
    elif isinstance(column_type, Date):
        value = date.fromisoformat(value)
    elif isinstance(column_type, Time):
        value = time.fromisoformat(value)
    elif isinstance(column_type, JSON):
        value = json.loads(value)
    elif isinstance(column_type, (String, Text)):
        if not isinstance(value, str):
            raise ValueError("Valore testuale non valido")
    else:
        raise ValueError("Tipo colonna non supportato per il backup legacy")
    return encode_value(value, column_type)


def _insert(tokens: list[str]) -> tuple[str, list[str], list[list[Any]]]:
    if len(tokens) < 8 or [token.upper() for token in tokens[:2]] != ["INSERT", "INTO"]:
        raise ValueError("INSERT legacy non valido")
    index = 2
    table_name = _identifier(tokens[index])
    index += 1
    if tokens[index] == ".":
        if table_name != "public":
            raise ValueError("Sono supportate solo tabelle nello schema public")
        table_name = _identifier(tokens[index + 1])
        index += 2
    if tokens[index] != "(":
        raise ValueError("Il dump deve essere generato con --column-inserts")
    index += 1
    columns = []
    while True:
        columns.append(_identifier(tokens[index]))
        index += 1
        if tokens[index] == ")":
            index += 1
            break
        if tokens[index] != ",":
            raise ValueError("Elenco colonne INSERT non valido")
        index += 1
    if len(set(columns)) != len(columns) or tokens[index].upper() != "VALUES":
        raise ValueError("Colonne duplicate o INSERT senza VALUES")
    index += 1
    rows = []
    while index < len(tokens):
        if tokens[index] != "(":
            raise ValueError("VALUES non valido")
        index += 1
        values = []
        while True:
            values.append(_literal(tokens[index]))
            index += 1
            if tokens[index] == ")":
                index += 1
                break
            if tokens[index] != ",":
                raise ValueError("Espressione SQL non supportata in VALUES")
            index += 1
        if len(values) != len(columns):
            raise ValueError("Numero valori e colonne INSERT diverso")
        rows.append(values)
        if index < len(tokens):
            if tokens[index] != "," or index == len(tokens) - 1:
                raise ValueError("Contenuto dopo VALUES non supportato")
            index += 1
    if not rows:
        raise ValueError("INSERT privo di valori")
    return table_name, columns, rows


def convert_legacy_backup(sql: str, metadata: Any, output: Path) -> None:
    if (
        not isinstance(metadata, dict)
        or metadata.get("format") != "home-inventory-backup-v2"
        or not isinstance(metadata.get("db_alembic_version"), str)
        or not metadata["db_alembic_version"]
        or not isinstance(metadata.get("created_at"), str)
    ):
        raise ValueError("Metadati legacy mancanti o formato non supportato")
    datetime.fromisoformat(metadata["created_at"].replace("Z", "+00:00"))
    header = sql.splitlines()[0] if sql else ""
    if header.startswith("-- HI_BACKUP_META: "):
        embedded = json.loads(header.removeprefix("-- HI_BACKUP_META: "))
        if not isinstance(embedded, dict) or any(
            embedded.get(key) != metadata[key]
            for key in ("format", "created_at", "db_alembic_version")
        ):
            raise ValueError("I metadati incorporati nel SQL non corrispondono al file JSON")

    records = []
    revisions = []
    tables = set()
    admin_id = None
    try:
        for number, tokens in enumerate(_statements(sql), start=1):
            command = tokens[0].upper()
            if command != "INSERT":
                # These pg_dump commands are discarded, never executed.
                normalized = " ".join(tokens)
                if (
                    command == "SET"
                    or re.fullmatch(
                        r'ALTER TABLE (?:public \. )?(?:"[^"]+"|\w+) '
                        r'(?:DISABLE|ENABLE) TRIGGER ALL', normalized, re.IGNORECASE
                    )
                    or re.fullmatch(
                        r"SELECT pg_catalog \. (?:setval|set_config) \( .* \)",
                        normalized, re.IGNORECASE | re.DOTALL
                    )
                ):
                    continue
                raise ValueError(f"Istruzione {number} non supportata ({command})")
            table_name, columns, rows = _insert(tokens)
            if table_name == "alembic_version":
                if columns != ["version_num"]:
                    raise ValueError("Tabella versione Alembic non valida")
                revisions.extend(row[0] for row in rows)
                continue
            table = Base.metadata.tables.get(table_name)
            if table is None:
                raise ValueError(f"Tabella legacy non supportata: {table_name}")
            unknown_columns = set(columns) - set(table.c.keys())
            if unknown_columns:
                raise ValueError(f"Colonne legacy non supportate nella tabella {table_name}")
            tables.add(table_name)
            for values in rows:
                row = {
                    name: _typed_value(value, table.c[name].type)
                    for name, value in zip(columns, values)
                }
                records.append({"table": table_name, "row": row})
                if table_name == "users" and row.get("username") == "admin":
                    admin_id = row.get("id")
    except (IndexError, TypeError, ArithmeticError) as exc:
        raise ValueError("Dati SQL legacy non validi") from exc
    if revisions != [metadata["db_alembic_version"]]:
        raise ValueError("La revisione Alembic del SQL non corrisponde ai metadati")
    if not records:
        raise ValueError("Il backup SQL non contiene dati applicativi")
    converted_metadata = {
        **metadata,
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "db_type": "POSTGRES",
        "converted_from": "home-inventory-backup-v2",
        "tables": sorted(tables),
        "admin_user_id": admin_id,
    }
    write_backup_archive(output, converted_metadata, records)
