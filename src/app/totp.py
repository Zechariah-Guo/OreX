"""TOTP utility functions for two-factor authentication."""

import base64
import secrets
import string
from io import BytesIO

import pyotp
import qrcode
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from werkzeug.security import check_password_hash, generate_password_hash


def generate_secret() -> str:
    """Generate a new base32-encoded TOTP secret using pyotp."""
    return pyotp.random_base32()


def get_provisioning_uri(secret: str, username: str) -> str:
    """Build otpauth://totp/OreX:{username}?secret={secret}&issuer=OreX"""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name="OreX")


def generate_qr_code(uri: str) -> bytes:
    """Render provisioning URI as a PNG QR code image (returns raw bytes)."""
    img = qrcode.make(uri)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def verify_totp(secret: str, code: str) -> bool:
    """Verify a 6-digit code with valid_window=1 (accepts +/- one period)."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def derive_fernet_key(app_secret_key: str) -> bytes:
    """Derive a 32-byte Fernet key from SECRET_KEY using PBKDF2-HMAC-SHA256."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"orex-totp-key",
        iterations=100000,
    )
    key = kdf.derive(app_secret_key.encode("utf-8"))
    return base64.urlsafe_b64encode(key)


def encrypt_secret(plaintext: str, app_secret_key: str) -> str:
    """Encrypt TOTP secret using Fernet with key derived from app SECRET_KEY."""
    key = derive_fernet_key(app_secret_key)
    f = Fernet(key)
    token = f.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str, app_secret_key: str) -> str:
    """Decrypt stored TOTP secret. Returns plaintext base32 string."""
    key = derive_fernet_key(app_secret_key)
    f = Fernet(key)
    plaintext = f.decrypt(ciphertext.encode("utf-8"))
    return plaintext.decode("utf-8")


def generate_backup_codes(count: int = 8) -> list[str]:
    """Generate `count` cryptographically random 8-char alphanumeric codes."""
    alphabet = string.ascii_letters + string.digits
    codes: list[str] = []
    while len(codes) < count:
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        if code not in codes:
            codes.append(code)
    return codes


def hash_backup_code(code: str) -> str:
    """Hash a backup code using Werkzeug generate_password_hash."""
    return generate_password_hash(code)


def verify_backup_code(stored_hash: str, code: str) -> bool:
    """Check a plaintext backup code against its stored hash."""
    return check_password_hash(stored_hash, code)
