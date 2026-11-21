import sys
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from cybernews_runtime.audit import add_event
from cybernews_runtime.database import Database
from cybernews_runtime.security import Role

from .accounts import add_user, govern
from .config import settings
from .models import AuthAudit, User
from .passwords import hasher
from .schemas import Registration


class BootstrapError(Exception):
    """Safe operator-facing bootstrap message."""


def already_initialized(db):
    return db.scalar(select(User.id).where(User.role == Role.SUPER_ADMIN).limit(1)) is not None


def create_first_admin(data: Registration, admin_password: str):
    if not 12 <= len(admin_password) <= 128 or data.password.get_secret_value() == admin_password:
        raise BootstrapError("Use a different administrative password of 12–128 characters.")
    database = Database(settings.database_url)
    try:
        with database.sessions.begin() as db:
            govern(db)
            if already_initialized(db):
                raise BootstrapError("A Super Admin already exists. Use the authorized role management API.")
            user = add_user(db, data, Role.SUPER_ADMIN, hasher.hash(admin_password))
            db.flush()
            add_event(db, AuthAudit, user.id, "super_admin_bootstrap", user.id)
            return user.id
    finally:
        database.engine.dispose()


def main():
    database = Database(settings.database_url)
    try:
        with database.sessions() as db:
            if already_initialized(db):
                raise BootstrapError("A Super Admin already exists. Use the authorized role management API.")
        if not (sys.stdin.isatty() and sys.stderr.isatty()):
            raise BootstrapError("An interactive terminal is required.")
        email = input("Email: ").strip()
        nickname = input("Nickname: ").strip()
        password = getpass("Account password: ")
        admin_password = getpass("Administrative password: ")
        if password != getpass("Confirm account password: ") or admin_password != getpass("Confirm administrative password: "):
            raise BootstrapError("Password confirmation does not match.")
        data = Registration(email=email, nickname=nickname, password=password)
        print(f"Created Super Admin {create_first_admin(data, admin_password)}")
    except BootstrapError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValidationError:
        print("Invalid email, nickname or account password.", file=sys.stderr)
        return 1
    except IntegrityError:
        print("The email or nickname is already in use.", file=sys.stderr)
        return 1
    except (SQLAlchemyError, EOFError, KeyboardInterrupt):
        print("Super Admin setup could not be completed.", file=sys.stderr)
        return 1
    finally:
        database.engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
