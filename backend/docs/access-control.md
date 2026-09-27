# DatumLex - Update and access guide

Edition: 2026-09-27. Windows / PowerShell.

## Update and access guide

DatumLex | Edition 27 September 2026 | Windows / PowerShell

This guide covers upgrading an installation that already runs without login, preparing a fresh installation, and operating authentication and user management. Switching branches alone is not enough: configure the environment, apply the required migrations, and restart both services.

### What changes

The frontend uses Django sessions and persisted users. Analytics require an authenticated, active, approved account with access to the selected court. Login accepts email or CPF; suport is the only username login.

All profiles open Menu after login or session restoration. If a password change is required, the user must complete it before accessing Menu. The main Tribunal filter shows only authorized courts; there is no duplicate filter above the dashboard.

### Prerequisites and scope

Use Python 3.12 and Node compatible with the installed Vite (20.19+ or 22.12+). Existing installations should keep their virtual environment and database configuration. Commands use C:\projetos\datumlex-core as an example; replace it with the actual repository path.

TJDFT is currently the only implemented analytics integration and initial court catalog entry. Updating the code does not copy databases, import judicial records, or add other court integrations. The backend selects PostgreSQL through DATABASE_URL; otherwise it uses backend/data/datumlex_v2.sqlite3.

### Reading order

Pages 2-3: upgrade an existing installation. Page 4: start services or prepare a fresh installation. Page 5: users and password policy. Page 6: API and audit. Page 7: validation and troubleshooting.

## 1. Prepare the existing installation

### Stop services and preserve local configuration

Stop Django and Vite with Ctrl+C in their terminals. Save uncommitted work before changing branches. Back up the database and the existing backend/.env using your current database backup procedure. Keep DATABASE_URL, DATAJUD_API_KEY, and DJANGO_SECRET_KEY unchanged during this update.

For SQLite, copy the actual database after stopping processes that write to it. For PostgreSQL, use a database backup, not a copy of the application folder. Do not overwrite an existing .env with .env.example.

### Obtain the feature code

The team must first publish the branch or deliver the complete code. This guide does not publish it. Replace FEATURE_BRANCH with the actual published name; do not type the placeholder literally. If the branch does not exist locally, create a tracking branch from its published remote branch.

```powershell
cd "C:\projetos\datumlex-core"
git status
git fetch origin
git switch FEATURE_BRANCH
git pull --ff-only
```

### Refresh dependencies and inspect migrations

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py showmigrations warehouse
```

For the simple upgrade path, 0001_initial and 0002_resource_schema must already be marked [X] in warehouse. The new authentication migrations do not alter existing judicial records in this v2 database.

STOP if the existing database is v1 or 0002_resource_schema is pending: that older migration drops and rebuilds warehouse tables and does not preserve v1 records. Follow backend/docs/resource-schema.md and plan a separate v2 database/data reload. Do not run the next migration step against a v1 database whose records must be retained.

## 2. Configure and apply the update

### Edit the existing backend/.env

Set DATUMLEX_SUPPORT_PASSWORD to the support credential agreed with the deployment owner. The examples intentionally use a placeholder: obtain the real value separately and replace it before migrating. Do not put the actual secret in source code, commits, or frontend variables.

```powershell
notepad .env

# Replace the placeholder with the agreed credential.
DATUMLEX_SUPPORT_PASSWORD=REPLACE_WITH_AGREED_SECRET
```

Use exact frontend origins for CORS and CSRF. For a local frontend on 127.0.0.1:5174, add or update the following entries. If using localhost or port 5173, adjust both values to match the browser URL. Multiple origins are comma-separated on one line.

```powershell
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5174
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:5174
```

### Apply migrations and provision support

```powershell
.\.venv\Scripts\python.exe manage.py migrate --plan
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py bootstrap_support
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py showmigrations accounts
```

Review the plan before executing it. Expected new components include contenttypes, auth, accounts, and sessions. The accounts migrations 0001_initial and 0002_protect_support should be marked [X]; check should report no issues.

With the support variable configured, the post-migration hook creates suport as an active approved Master. bootstrap_support confirms provisioning and reports an error if a new account needs a missing credential. Re-running either command does not reset an existing support password. Changing .env afterwards does not change the stored password.

## 3. Start and verify the application

### Backend - terminal 1

```powershell
cd "C:\projetos\datumlex-core\backend"
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

### Frontend - terminal 2

```powershell
cd "C:\projetos\datumlex-core\frontend"
npm ci
npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Open http://127.0.0.1:5174/. strictPort prevents an automatic port change that would mismatch the configured origins. If the port is occupied, stop the previous frontend or deliberately select and configure another port.

Sign in as suport using the deployment-configured password. Menu should open. Open Usuários to create an account or approve a pending registration and select its courts. Sign out and verify the ordinary account. The /api/health/ endpoint remains public; protected analytics should deny anonymous access.

### Compiled frontend and production

If the installation serves compiled files, run npm run build and replace the served frontend/dist assets. Vite development proxy forwards /api to port 8000; a static production build requires a reverse proxy or VITE_API_BASE_URL set before building.

Production requires HTTPS, DJANGO_DEBUG=false, a unique DJANGO_SECRET_KEY, and exact allowed hosts/origins. Session and CSRF cookies become Secure with debug disabled. runserver is for local development.

### Fresh installation only

Obtain the complete code, then run the commands below inside backend. Configure .env as described on page 3, apply migrations, provision support, and start both services. Never use the copy command below to overwrite an existing .env. A fresh database contains no judicial records; import/extract them using the backend README.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

## 4. Accounts, roles and passwords

### Registration and approval

Public registration requires full name, valid CPF, email, password, and password confirmation in the interface. CPF and email cannot be reused; email uniqueness is case-insensitive. A new self-registered account is Standard, pending approval, without courts, and does not require an initial password change.

Master manages all ordinary profiles and may delete users. Admin lists users, but only creates, edits, approves, and assigns courts to Standard accounts; it cannot delete users or assign Master/Admin. Standard accesses only Menu/consultations. Management prevents removal of the signed-in user's own access.

### Password change rules

Ordinary passwords require at least eight characters; numbers and symbols are optional. The administrative creation form defaults to Exigir alteração de senha no primeiro acesso checked. The creator may uncheck it. The creation API accepts a boolean must_change_password and defaults to true.

When Master edits a password, both new-password fields must match. Leaving them empty preserves the password. Every manual reset activates mandatory change at the next access, invalidates the target's existing sessions, and writes an audit event without the password. Admin cannot reset passwords. A Master resetting their own password keeps the current session but must also complete the change.

### Support exception

suport is hidden from user lists, counts, filters, and edit/delete operations. It automatically accesses all catalog courts. Other users, including ordinary Masters, require explicit court permissions checked by the backend.

The agreed support password is an explicit exception to minimum length and rotation: it is immutable and never triggers first-access change. The secret is configured privately and stored as a hash. API checks, model rules, a protected foreign key, and SQLite/PostgreSQL triggers block support deletion or changes to its username, support flag, role, approval, active state, password hash, and required-change flag. Database owners remain outside this application-level protection.

## 5. API and audit reference

All API paths except health, CSRF initialization, login, and registration require an active approved session. While password change is mandatory, only current-user, logout, and password-change internal routes are permitted. The frontend sends cookies and CSRF headers.

GET /api/auth/csrf/ - Initialize CSRF token/cookie.

POST /api/auth/register/ - Create pending public registration.

POST /api/auth/login/ - Sign in and rotate session/CSRF.

POST /api/auth/logout/ - End session.

GET /api/auth/me/ - Current account and court catalog.

POST /api/auth/password/ - Change ordinary account password.

GET / POST /api/users/ - List/filter or create accounts.

PATCH / DELETE /api/users/<id>/ - Edit/approve or delete an account.

GET /api/audit/ - Read latest 200 events, Master only.

Management filters: q, role, pending=true. POST/PATCH/DELETE require CSRF, including public login and registration. Analytics endpoints scope, statistics, distribution, instances, and processes enforce the selected court before querying. API clients that previously called analytics anonymously must now authenticate and retain session cookies.

### Audit and attempt limits

Mutations record audit events in the same database transaction. Login outcomes, logout, password changes, and Master password resets are logged. Support API requests additionally record method, path, and status. Permission updates retain before/after role, status, and courts. Passwords and request bodies are not logged.

Audit records survive deletion of the user and retain actor name. Database-backed login/registration limits use hashed identity/IP keys and 15-minute windows. Repeated failed attempts may temporarily block login.

## 6. Validation and troubleshooting

### Optional development checks

Inside backend, install development dependencies and run isolated tests. The PostgreSQL variant creates a uniquely named temporary test database and removes it afterwards; its database user needs permission to create test databases.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe manage.py test tests `
  --settings=config.test_settings
# PostgreSQL alternative:
.\.venv\Scripts\python.exe manage.py test tests `
  --settings=config.postgres_test_settings
```

Test settings use a fast test-only password hasher. Normal application settings retain Django production hashers. In frontend, run npm run lint and npm run build. tests/access-live.mjs uses Playwright and Edge, creates temporary accounts, removes them after testing, and retains audit events. It needs PLAYWRIGHT_MODULE, DATUMLEX_SUPPORT_PASSWORD, and optionally FRONTEND_URL. Supply secrets through the environment, not command arguments or source files.

### Common problems

No login screen: confirm the frontend serves this revision, restart Vite, or rebuild and redeploy dist. Login route returns 404: restart the old backend, especially if it was started with --noreload.

CSRF error: check exact protocol/host/port in CSRF_TRUSTED_ORIGINS, restart Django, and refresh the browser. Missing tables: check the selected database and migration status. Support unavailable: configure the initial secret and run bootstrap_support; this cannot reset an existing password.

Pending account: a permitted Master/Admin must approve it. No court available: assign court access in user management. Empty analytics: confirm DATABASE_URL still points to the intended database and that it contains loaded records. Rate limit reached: wait 15 minutes. Do not delete tables or reapply old warehouse migrations to solve these symptoms.

### Source of truth

Repository: backend/docs/access-control.md (English), backend/docs/resource-schema.md, backend/.env.example, config/settings.py, src/accounts, and frontend/src/AccessApp.jsx. This edition replaces earlier unauthenticated-access instructions; it does not replace the DataJud extraction manual.
