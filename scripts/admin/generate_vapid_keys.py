"""Generate a VAPID key pair for Web Push (one-off).

Run:  .venv\\Scripts\\python.exe scripts/admin/generate_vapid_keys.py

Prints three lines to paste into .env (or the server's environment):

    VAPID_PUBLIC_KEY=...    base64url uncompressed P-256 point, sent to browsers
    VAPID_PRIVATE_KEY=...   base64url raw 32-byte private value, server only
    VAPID_SUBJECT=mailto:you@example.com   edit this to a real contact

The private key is printed here and nowhere else. Keep it out of git and logs.
If you replace the pair later, every device has to enable notifications again.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def generate():
    """Return (public_key, private_key) as base64url strings."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, 'big')
    public = key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url(public), _b64url(private)


if __name__ == '__main__':
    public_key, private_key = generate()
    print(f'VAPID_PUBLIC_KEY={public_key}')
    print(f'VAPID_PRIVATE_KEY={private_key}')
    print('VAPID_SUBJECT=mailto:orexsupport@gmail.com')
