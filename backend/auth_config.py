"""Resolve the installation JWT key without exposing it in logs."""

from functools import lru_cache
import logging
import os
from pathlib import Path
import secrets
import stat
import tempfile

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv(Path(__file__).with_name(".env"), override=False)


def validate_secret(value: str) -> str:
    value = value.strip()
    if value.upper() == "AUTO" or len(value.encode("utf-8")) < 32:
        raise RuntimeError("SECRET_KEY must contain at least 32 bytes; use a random key or AUTO.")
    return value


def read_secret(path: Path, *, private: bool = False) -> str:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise RuntimeError("JWT secret must be a regular file.")
            if private and stat.S_IMODE(info.st_mode) & 0o077:
                raise RuntimeError("Generated JWT secret must be accessible only to its owner.")
            return validate_secret(stream.read())
    except (OSError, UnicodeError):
        raise RuntimeError("Cannot read JWT secret file; check its path and permissions.") from None


def persistent_secret(path: Path) -> tuple[str, bool]:
    try:
        if path.exists() or path.is_symlink():
            return read_secret(path, private=True), False
        path.parent.mkdir(parents=True, exist_ok=True)
        # Publish only a fully written file; concurrent processes use the same winner.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".jwt-secret-", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(secrets.token_urlsafe(64))
                stream.flush()
                os.fsync(stream.fileno())
                try:
                    os.link(temporary, path)
                    generated = True
                except FileExistsError:
                    generated = False
            finally:
                temporary.unlink(missing_ok=True)
        return read_secret(path, private=True), generated
    except OSError:
        raise RuntimeError("Cannot persist JWT secret; provide writable persistent storage or SECRET_KEY_FILE.") from None


@lru_cache(maxsize=1)
def get_secret_key() -> str:
    configured = os.environ.get("SECRET_KEY", "").strip()
    file_name = os.environ.get("SECRET_KEY_FILE", "").strip()
    try:
        if file_name:
            if configured and configured.upper() != "AUTO":
                raise RuntimeError("Set only one of SECRET_KEY and SECRET_KEY_FILE.")
            result = read_secret(Path(file_name))
            logger.warning("JWT key loaded from SECRET_KEY_FILE; key value is never logged.")
        elif configured and configured.upper() != "AUTO":
            result = validate_secret(configured)
            logger.warning("JWT key supplied by configuration; key value is never logged.")
        else:
            path = Path(__file__).parent / "data" / "jwt-secret.key"
            result, generated = persistent_secret(path)
            logger.warning(
                "JWT key %s at %s. Keep this file on persistent storage; "
                "configure SECRET_KEY or SECRET_KEY_FILE to manage it externally. Key value is never logged.",
                "generated" if generated else "reused", path,
            )
        return result
    except RuntimeError as exc:
        logger.error("JWT key configuration error: %s", exc)
        raise


ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "14400"))
