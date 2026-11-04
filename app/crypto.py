import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_SALT = b"zhihu-collect-web-v1"
_INFO = b"encrypted-secrets"


def _fernet(secret_key):
    if not secret_key:
        raise ValueError("SECRET_KEY 不能为空")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        info=_INFO,
    )
    key = hkdf.derive(secret_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(secret_key, plaintext):
    return _fernet(secret_key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(secret_key, token):
    if not token:
        return None
    try:
        return _fernet(secret_key).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None
