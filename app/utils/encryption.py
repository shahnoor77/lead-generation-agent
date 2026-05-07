"""
Simple symmetric encryption for SMTP passwords.
Uses Fernet (AES-128-CBC + HMAC) from the cryptography library.
Falls back to base64 obfuscation if cryptography is not installed.
"""

from __future__ import annotations
import base64
import hashlib
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

try:
    from cryptography.fernet import Fernet
    # Derive a 32-byte key from the secret_key
    _key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.secret_key.encode()).digest()
    )
    _fernet = Fernet(_key)
    _USE_FERNET = True
except ImportError:
    _USE_FERNET = False
    logger.warning("encryption.fernet_unavailable", reason="cryptography not installed — using base64 obfuscation")


def encrypt(plaintext: str) -> str:
    if _USE_FERNET:
        return _fernet.encrypt(plaintext.encode()).decode()
    return base64.b64encode(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if _USE_FERNET:
        return _fernet.decrypt(ciphertext.encode()).decode()
    return base64.b64decode(ciphertext.encode()).decode()
