"""Reset a user's password from an interactive container terminal."""

import argparse
from datetime import datetime, timezone
import getpass
import sys
import warnings

from sqlalchemy.exc import SQLAlchemyError

from auth_config import key_lock
from database import SessionLocal
from models import DeviceSession, User
from routes.auth import hash_password


def reset_password(username: str, password: str) -> int:
    if not password or len(password.encode("utf-8")) > 72:
        raise ValueError("La password deve essere non vuota e non superare 72 byte UTF-8.")
    password_hash = hash_password(password)
    with key_lock(), SessionLocal.begin() as db:
        user = db.query(User).filter(User.username == username).with_for_update().first()
        if user is None:
            raise ValueError("Utente non trovato.")
        now = datetime.now(timezone.utc)
        db.query(User).filter(User.id == user.id).update({
            User.hashed_password: password_hash,
            User.auth_revoked_before: int(now.timestamp() * 1_000_000),
        }, synchronize_session=False)
        return db.query(DeviceSession).filter(
            DeviceSession.user_id == user.id,
            DeviceSession.revoked_at.is_(None),
        ).update({DeviceSession.revoked_at: now.replace(tzinfo=None)}, synchronize_session=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reimposta la password e revoca le sessioni dell'utente.")
    parser.add_argument("username", help="Nome utente esatto")
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print("Errore: e necessario un terminale interattivo per inserire la password.", file=sys.stderr)
        return 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Nuova password: ")
            confirmation = getpass.getpass("Ripeti password: ")
        if password != confirmation:
            raise ValueError("Le password non coincidono.")
        revoked = reset_password(args.username, password)
    except getpass.GetPassWarning:
        print("Errore: impossibile disattivare l'eco della password nel terminale.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nOperazione annullata.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Errore database: esito non confermato; verificare configurazione e log.", file=sys.stderr)
        return 1
    print(f"Password aggiornata. Sessioni revocate: {revoked}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
