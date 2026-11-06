from pathlib import Path
import re

API_VERSION = Path(__file__).with_name("VERSION").read_text(encoding="ascii").strip()
if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", API_VERSION):
    raise RuntimeError("Invalid backend/VERSION: expected a semantic release version.")
