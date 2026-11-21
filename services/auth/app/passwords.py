from secrets import token_urlsafe

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

hasher = PasswordHasher()
dummy_hash = hasher.hash(token_urlsafe(32))


def verify_password(password: str, stored_hash: str | None) -> bool:
    try:
        matches = hasher.verify(stored_hash or dummy_hash, password)
    except (VerificationError, InvalidHashError):
        return False
    return bool(stored_hash and matches)
