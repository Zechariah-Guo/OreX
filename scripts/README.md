# Scripts

Run from the repository root. Admin scripts use the app's configured database (`src/data/orex.db`; `/app/src/data/orex.db` in Docker). They only need the packages the app itself needs. Dev tools need the dev dependency group.

## admin/ (production management, also copied into the Docker image)

| Script | What it does |
|--------|--------------|
| `export_user_data.py USER [--output FILE]` | JSON copy of everything stored about a player (no secrets), for data access requests |
| `rename_user.py OLD NEW` | Renames a player (registration rules apply) and signs them out |
| `remove_avatar.py USER` | Deletes the uploaded avatar from storage and clears it; the player falls back to initials |
| `suspend_user.py USER [--reason TEXT]` | Blocks sign-in, signs the player out, hides them from the leaderboard and profiles, removes their push subscriptions |
| `unsuspend_user.py USER` | Lifts a suspension |
| `reset_password.py USER [--random] [--disable-2fa]` | Sets a new password (2FA and recovery key untouched). `--disable-2fa` also turns 2FA off for a player who lost their device and backup codes; they can turn it on again in Settings |
| `drop_user.py USER` | Permanently deletes an account and its data |
| `reset_economy.py [--dry-run] [--yes]` | Season reset: every player as in Settings > Reset Account, bots and ore prices back to start. Asks you to type RESET |
| `generate_vapid_keys.py` | Makes the Web Push VAPID key pair (run once) |
| `_admin_common.py` | Shared setup (not a script) |

Docker: `docker compose exec app python /app/scripts/admin/<script>.py ...`

## dev/ (development only, not in the Docker image)

| Script | What it does |
|--------|--------------|
| `screenshot.py` | Starts the app on a throwaway database and screenshots pages in headless Chrome/Edge. Its helpers are reused by the other browser tools and by `tests/test_tutorial_browser.py` |
| `safari_check.py` | Playwright WebKit pass over the main pages with iPhone/iPad presets (needs Playwright) |
| `pwa_check.py` | Real-browser check of the service worker and offline page (needs Playwright) |
