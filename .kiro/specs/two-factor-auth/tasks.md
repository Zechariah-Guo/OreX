# Implementation Plan: Two-Factor Authentication

## Overview

Add optional TOTP-based two-factor authentication to OreX. Implementation proceeds bottom-up: dependencies → schema → core TOTP module → model functions → routes → templates → integration into existing auth flow. Each step builds incrementally so the feature is testable at every stage.

## Tasks

- [x] 1. Add dependencies and update database schema
  - [x] 1.1 Add pyotp and qrcode to requirements.txt
    - Add `pyotp==2.9.0` and `qrcode==8.0` to `requirements.txt`
    - Run `pip install -r requirements.txt` to verify installation
    - _Requirements: 1.3, 1.4 (pyotp for TOTP generation, qrcode for QR rendering)_

  - [x] 1.2 Add 2FA columns and backup_codes table to schema.sql
    - Add `totp_enabled INTEGER NOT NULL DEFAULT 0` column to users table
    - Add `totp_secret_encrypted TEXT` column to users table
    - Create `backup_codes` table with columns: id, user_id, code_hash, used, created_at
    - Add index `idx_backup_codes_user` on backup_codes(user_id)
    - Add `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE`
    - _Requirements: 9.1, 3.3, 10.3_

- [x] 2. Implement core TOTP utility module
  - [x] 2.1 Create `src/app/totp.py` with secret generation and provisioning URI functions
    - Implement `generate_secret()` using `pyotp.random_base32()`
    - Implement `get_provisioning_uri(secret, username)` returning `otpauth://totp/OreX:{username}?secret={secret}&issuer=OreX`
    - Implement `generate_qr_code(uri)` using `qrcode` library, returning PNG bytes via BytesIO
    - _Requirements: 1.3, 1.4, 1.5_

  - [x] 2.2 Add TOTP verification function to `src/app/totp.py`
    - Implement `verify_totp(secret, code)` using `pyotp.TOTP(secret).verify(code, valid_window=1)`
    - Accepts current code, one period before, one period after
    - _Requirements: 2.4, 4.6_

  - [x] 2.3 Add encryption/decryption functions to `src/app/totp.py`
    - Implement `derive_fernet_key(app_secret_key)` using PBKDF2-HMAC-SHA256 with salt `b"orex-totp-key"` and 100,000 iterations
    - Implement `encrypt_secret(plaintext, app_secret_key)` using Fernet encryption
    - Implement `decrypt_secret(ciphertext, app_secret_key)` using Fernet decryption
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 2.4 Add backup code generation and hashing to `src/app/totp.py`
    - Implement `generate_backup_codes(count=8)` using `secrets.token_hex` or `secrets.choice` for 8-char alphanumeric codes
    - Implement `hash_backup_code(code)` using `werkzeug.security.generate_password_hash`
    - Implement `verify_backup_code(stored_hash, code)` using `werkzeug.security.check_password_hash`
    - _Requirements: 3.1, 3.3, 3.4, 9.4_

  - [x] 2.5 Write property tests for TOTP utility functions
    - **Property 1: Provisioning URI format** — Generate random usernames (alphanum 3-20 chars) and base32 secrets, verify URI matches `otpauth://totp/OreX:{username}?secret={secret}&issuer=OreX`
    - **Property 3: Backup code generation format** — Call `generate_backup_codes(8)` repeatedly, verify count=8, uniqueness, and format `^[A-Za-z0-9]{8}$`
    - **Property 4: Backup code hashing is non-reversible** — Generate random 8-char alphanumeric codes, verify hash != plaintext and `verify_backup_code(hash, code)` returns True
    - **Property 6: TOTP secret encryption round-trip** — Generate random base32 secrets and SECRET_KEYs, verify `decrypt(encrypt(s, k), k) == s` and ciphertext != plaintext
    - **Validates: Requirements 1.4, 3.1, 3.3, 3.4, 9.1**

  - [x] 2.6 Write property test for TOTP verification with clock skew
    - **Property 2: TOTP verification with clock skew** — Generate random secrets, compute codes at T-1, T, T+1 periods and verify acceptance; compute codes at T-2, T+2 and verify rejection
    - **Validates: Requirements 2.4, 4.6**

- [x] 3. Implement model functions for 2FA data access
  - [x] 3.1 Add 2FA state management functions to `src/app/models.py`
    - Implement `get_2fa_status(user_id)` returning `{enabled: bool, encrypted_secret: str|None}`
    - Implement `enable_2fa(user_id, encrypted_secret)` setting `totp_enabled=1` and storing encrypted secret
    - Implement `disable_2fa(user_id)` setting `totp_enabled=0`, clearing secret, and deleting all backup codes
    - Implement `get_encrypted_totp_secret(user_id)` fetching the encrypted TOTP secret
    - _Requirements: 8.3, 9.1_

  - [x] 3.2 Add backup code management functions to `src/app/models.py`
    - Implement `store_backup_codes(user_id, hashed_codes)` inserting into backup_codes table
    - Implement `get_backup_codes(user_id)` fetching all backup code rows (id, code_hash, used)
    - Implement `mark_backup_code_used(code_id)` setting `used=1`
    - Implement `delete_backup_codes(user_id)` removing all backup codes for a user
    - Implement `get_remaining_backup_code_count(user_id)` counting unused codes
    - _Requirements: 3.3, 5.2, 5.4_

  - [x] 3.3 Write property tests for model functions
    - **Property 5: Backup code single-use semantics** — Generate a code, store its hash, mark as used, verify subsequent attempts fail
    - **Property 9: Disabling 2FA removes all 2FA data** — Create user with 2FA, call `disable_2fa`, verify `totp_enabled=0`, secret is NULL, backup_codes count=0
    - **Property 10: Account reset preserves 2FA configuration** — Create user with 2FA and backup codes, call reset_account, verify 2FA state unchanged
    - **Property 11: Account delete removes all 2FA data** — Create user with 2FA, call delete_account, verify no rows remain in users or backup_codes
    - **Validates: Requirements 5.2, 8.3, 10.1, 10.3**

- [x] 4. Checkpoint - Core module and model verification
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement 2FA routes and templates
  - [x] 5.1 Create `src/app/routes/two_factor.py` with challenge routes
    - Create new blueprint `two_factor_bp`
    - Implement `GET /login/2fa` — render challenge page (check pending session exists and not expired, redirect to `/login` otherwise)
    - Implement `POST /login/2fa` — verify TOTP code, complete login via `login_user()`, redirect to dashboard
    - Implement `POST /login/2fa/backup` — verify backup code, mark as used, complete login
    - Apply existing rate limiter to all challenge endpoints
    - Validate pending session expiry (5-minute window)
    - _Requirements: 4.1, 4.2, 4.3, 4.5, 4.6, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3_

  - [x] 5.2 Add 2FA setup and disable routes to `src/app/routes/two_factor.py`
    - Implement `POST /settings/2fa/setup` — generate secret, render QR code + manual key (requires @login_required)
    - Implement `POST /settings/2fa/confirm` — verify TOTP code, enable 2FA, generate and display backup codes
    - Implement `POST /settings/2fa/disable` — verify TOTP/backup code, call `disable_2fa()`
    - _Requirements: 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 3.1, 3.2, 8.1, 8.2, 8.3, 8.4_

  - [x] 5.3 Create `src/templates/pages/two_factor_challenge.html`
    - Single input field for 6-digit TOTP code with submit button
    - Link/button to switch to backup code entry
    - Display error messages for invalid codes and rate limiting
    - Display remaining lockout time when rate limited
    - Extend `base.html`
    - _Requirements: 4.3, 4.4, 6.2_

  - [x] 5.4 Create `src/templates/pages/two_factor_setup.html`
    - Display QR code image (base64-encoded inline)
    - Display manual key as selectable text below QR code
    - Input field for 6-digit confirmation code
    - Error message area for invalid codes
    - On confirmation success: display 8 backup codes with clear warning they won't be shown again
    - Extend `base.html`
    - _Requirements: 1.4, 1.5, 2.1, 2.3, 3.2_

  - [x] 5.5 Update `src/templates/pages/settings.html` with 2FA security section
    - Add "Two-Factor Authentication" section in security area
    - Show current 2FA status (enabled/disabled)
    - Display "Enable 2FA" button when disabled
    - Display "Disable 2FA" button when enabled
    - _Requirements: 1.1, 1.2, 8.1_

- [x] 6. Integrate 2FA into existing auth flow
  - [x] 6.1 Modify `src/app/routes/auth.py` login route to redirect 2FA-enabled users
    - After password verification success, check `totp_enabled` for the user
    - If enabled: store `pending_2fa_user_id` and `pending_2fa_time` in session, redirect to `/login/2fa`
    - If disabled: proceed with normal `login_user()` flow (existing behavior unchanged)
    - Store only user_id and timestamp in session — NOT password or secret
    - _Requirements: 4.1, 4.2, 7.3_

  - [x] 6.2 Register `two_factor_bp` blueprint in `src/app/__init__.py`
    - Import and register the new blueprint in the app factory
    - _Requirements: 4.1_

  - [x] 6.3 Write property test for pending session expiry boundary
    - **Property 7: Pending session expiry boundary** — Generate random timestamps, verify session valid at T+299s, invalid at T+300s
    - **Validates: Requirements 7.1, 7.2**

- [x] 7. Checkpoint - Full feature integration verification
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Write integration tests
  - [x] 8.1 Write integration tests for login 2FA flow
    - Test full login flow: password → redirect to /login/2fa → valid TOTP → dashboard
    - Test login flow with backup code: password → redirect → valid backup code → dashboard
    - Test pending session blocks access to authenticated routes
    - Test expired pending session redirects to login
    - Test rate limiting shared counter across password and 2FA failures
    - _Requirements: 4.1, 4.2, 4.5, 5.1, 6.1, 6.3, 7.1, 7.2_

  - [x] 8.2 Write integration tests for 2FA setup and disable flows
    - Test enable 2FA end-to-end: setup → confirm with valid code → backup codes displayed
    - Test disable 2FA end-to-end: enter valid code → 2FA removed → login without challenge
    - Test setup rejects invalid TOTP code without regenerating secret
    - Test account reset preserves 2FA (login after reset still requires challenge)
    - Test account delete removes all 2FA data (no orphaned backup_codes rows)
    - _Requirements: 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 8.2, 8.3, 10.1, 10.3_

- [ ] 9. Final checkpoint - Complete test suite passes
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The existing rate limiter is reused — no new rate limit infrastructure needed
- Pillow is already in requirements.txt so qrcode PNG rendering works out of the box
- The `ON DELETE CASCADE` on backup_codes handles account deletion cleanup at the DB level

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["2.5", "2.6", "3.1", "3.2"] },
    { "id": 4, "tasks": ["3.3", "5.1", "5.2"] },
    { "id": 5, "tasks": ["5.3", "5.4", "5.5"] },
    { "id": 6, "tasks": ["6.1", "6.2"] },
    { "id": 7, "tasks": ["6.3", "8.1", "8.2"] }
  ]
}
```
