# Fleet report contract (CC-079)

What Command Center (`ccd/fleet.py`, `GET /api/fleet`) asks each app, and what the app must answer. Each app
implements its side in its own repository, reviewed there; Command Center never queries an app's database.

## Request

`GET http://127.0.0.1:<port>/api/internal/fleet/v1/accounts` with `Authorization: Bearer <token>`.
The token is read from the file named in `registry.py` (`fleet.token_file`), created by Jay, mode 0600.
Registered today: SamVision `127.0.0.1:8502`, MyFamilyExpenses `127.0.0.1:3002`.

## Reply (200, JSON, at most 4096 bytes, exactly these keys)

    {"accounts": 12, "active": 7, "active_window_days": 30}

- `accounts`: rows in the app's accounts table. Accounts, not people: one person with two logins counts twice.
- `active`: accounts that signed in or made an authenticated request in the last 30 days. `0 <= active <= accounts`.
- `active_window_days`: must be 30. Command Center shows one written definition beside every active number; an app
  that uses another window is listed as did-not-respond.
- The app answers from a read-only transaction and returns counts only: no names, emails, ids or other fields.
  Without the token it answers 401.

Anything else (extra or missing key, non-integer, too large, redirect, timeout over 3 s) counts as "did not respond".

## GYST

One user by design, so it has no counts endpoint. It is listed as `single-user`, outside the total; its health comes
from `docker ps` status (`healthy`, `unhealthy`, `running`, `unknown`).
