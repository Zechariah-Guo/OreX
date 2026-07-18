"""Property-based tests for TOTP utility functions.

Tests the core TOTP utility functions in app/totp.py using Hypothesis
for property-based testing with minimum 100 iterations per property.
"""

import re
import string

from hypothesis import given, settings
from hypothesis import strategies as st

from app.totp import (
    decrypt_secret,
    encrypt_secret,
    generate_backup_codes,
    get_provisioning_uri,
    hash_backup_code,
    verify_backup_code,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Alphanumeric usernames between 3 and 20 characters
username_strategy = st.text(
    alphabet=string.ascii_letters + string.digits,
    min_size=3,
    max_size=20,
)

# Valid base32 secrets (uppercase letters A-Z and digits 2-7, length 16 or 32)
base32_secret_strategy = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ234567",
    min_size=16,
    max_size=32,
).filter(lambda s: len(s) % 8 == 0)

# Random 8-char alphanumeric codes (same format as backup codes)
alphanumeric_code_strategy = st.text(
    alphabet=string.ascii_letters + string.digits,
    min_size=8,
    max_size=8,
)

# SECRET_KEY strategy: non-empty strings for Fernet key derivation
secret_key_strategy = st.text(
    alphabet=string.ascii_letters + string.digits + string.punctuation,
    min_size=8,
    max_size=64,
)


# ---------------------------------------------------------------------------
# Feature: two-factor-auth, Property 1: Provisioning URI format
# Validates: Requirements 1.4
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    username=username_strategy,
    secret=base32_secret_strategy,
)
def test_provisioning_uri_format(username, secret):
    """Property 1: For any valid username (alphanum 3-20 chars) and base32
    secret, the provisioning URI matches
    otpauth://totp/OreX:{username}?secret={secret}&issuer=OreX
    """
    uri = get_provisioning_uri(secret, username)

    expected = f"otpauth://totp/OreX:{username}?secret={secret}&issuer=OreX"
    assert uri == expected, f"Expected: {expected}\nGot: {uri}"


# ---------------------------------------------------------------------------
# Feature: two-factor-auth, Property 3: Backup code generation format
# Validates: Requirements 3.1, 3.4
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(st.just(8))
def test_backup_code_generation_format(count):
    """Property 3: For any invocation of generate_backup_codes(8), the result
    contains exactly 8 elements, each is exactly 8 characters matching
    ^[A-Za-z0-9]{8}$, and all 8 are distinct.
    """
    codes = generate_backup_codes(count)

    # Exactly 8 codes
    assert len(codes) == 8

    # All codes are unique
    assert len(set(codes)) == 8

    # Each code matches the expected format
    pattern = re.compile(r"^[A-Za-z0-9]{8}$")
    for code in codes:
        assert pattern.match(code), f"Code '{code}' does not match ^[A-Za-z0-9]{{8}}$"


# ---------------------------------------------------------------------------
# Feature: two-factor-auth, Property 4: Backup code hashing is non-reversible
# Validates: Requirements 3.3, 9.4
# ---------------------------------------------------------------------------

@settings(max_examples=100, deadline=None)
@given(code=alphanumeric_code_strategy)
def test_backup_code_hashing_non_reversible(code):
    """Property 4: For any generated 8-char alphanumeric code, hash_backup_code
    produces a string != the plaintext, and verify_backup_code(hash, code)
    returns True.
    """
    hashed = hash_backup_code(code)

    # Hash is not equal to the plaintext
    assert hashed != code, "Hash should not equal the plaintext code"

    # Verification succeeds
    assert verify_backup_code(hashed, code) is True, (
        "verify_backup_code should return True for the correct code"
    )


# ---------------------------------------------------------------------------
# Feature: two-factor-auth, Property 6: TOTP secret encryption round-trip
# Validates: Requirements 9.1
# ---------------------------------------------------------------------------

@settings(max_examples=100, deadline=None)
@given(
    secret=base32_secret_strategy,
    app_secret_key=secret_key_strategy,
)
def test_totp_secret_encryption_round_trip(secret, app_secret_key):
    """Property 6: For any valid base32 secret and any SECRET_KEY,
    decrypt(encrypt(s, k), k) == s and encrypt(s, k) != s.
    """
    ciphertext = encrypt_secret(secret, app_secret_key)

    # Ciphertext is not equal to plaintext
    assert ciphertext != secret, "Ciphertext should not equal the plaintext secret"

    # Round-trip: decrypt(encrypt(s, k), k) == s
    decrypted = decrypt_secret(ciphertext, app_secret_key)
    assert decrypted == secret, (
        f"Round-trip failed: expected '{secret}', got '{decrypted}'"
    )
