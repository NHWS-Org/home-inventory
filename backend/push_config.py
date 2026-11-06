"""Installation-owned VAPID key, independent from JWT and database backups."""

import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.exceptions import UnsupportedAlgorithm

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


class PushConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, repr=False)
class PushConfig:
    private_key: ec.EllipticCurvePrivateKey
    public_key: str
    fingerprint: str
    subject: str


def load_push_config() -> PushConfig | None:
    enabled = os.getenv("WEB_PUSH_ENABLED", "false").lower()
    if enabled not in ("true", "false"):
        raise PushConfigurationError("WEB_PUSH_ENABLED must be true or false")
    if enabled == "false":
        return None
    path = os.getenv("WEB_PUSH_VAPID_PRIVATE_KEY_FILE", "")
    subject = os.getenv("WEB_PUSH_VAPID_SUBJECT", "")
    try:
        parsed = urlsplit(subject)
    except ValueError:
        raise PushConfigurationError("Invalid VAPID contact subject") from None
    if (
        not path or len(subject) > 255 or any(char.isspace() for char in subject)
        or not (
            parsed.scheme == "mailto" and "@" in parsed.path
            or parsed.scheme == "https" and parsed.hostname and not parsed.username
        )
    ):
        raise PushConfigurationError("Configure a persistent VAPID PEM key and valid contact subject")
    try:
        private = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm):
        raise PushConfigurationError("Cannot read the configured VAPID private key") from None
    if not isinstance(private, ec.EllipticCurvePrivateKey) or not isinstance(
        private.curve, ec.SECP256R1,
    ):
        raise PushConfigurationError("VAPID requires a P-256 private key")
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    return PushConfig(
        private, base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii"),
        hashlib.sha256(public).hexdigest(), subject,
    )
