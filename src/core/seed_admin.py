"""Seeds a standard admin account for local dev/testing so you don't have
to sign up fresh every time the DB gets reset. Idempotent - safe to rerun.

    uv run python -m core.seed_admin

The generated password is written to .admin_credentials (gitignored, repo
root) rather than printed into any chat/log that might get persisted -
read that file to log in.
"""

import secrets
from pathlib import Path

from core.auth import hash_password
from core.db import SessionLocal, init_db
from core.models_db import User

ADMIN_EMAIL = "admin@example.com"
CREDENTIALS_FILE = Path(__file__).resolve().parent.parent.parent / ".admin_credentials"


def seed_admin() -> None:
    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if existing is not None:
            print(f"Admin account already exists: {ADMIN_EMAIL}")
            if CREDENTIALS_FILE.exists():
                print(f"Password is in {CREDENTIALS_FILE}")
            else:
                print("Password file is missing - delete the admin user's DB row and rerun to reseed.")
            return

        password = secrets.token_urlsafe(18)
        user = User(email=ADMIN_EMAIL, password_hash=hash_password(password))
        db.add(user)
        db.commit()

        CREDENTIALS_FILE.write_text(f"{ADMIN_EMAIL}\n{password}\n")
        CREDENTIALS_FILE.chmod(0o600)
        print(f"Created admin account: {ADMIN_EMAIL}")
        print(f"Password written to {CREDENTIALS_FILE}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_admin()
