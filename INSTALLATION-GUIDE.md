# How to Run DatumLex on Windows

This guide explains how to download the project, set up PostgreSQL, and run the Django backend and React frontend. Use **PowerShell**, run each block in the specified folder, and proceed only when it completes without errors.

## 1. Required Software

| Software | Purpose | Official Download |
| --- | --- | --- |
| Git | Download the code from GitHub | [Git for Windows](https://git-scm.com/downloads/win) |
| Python 3.12 or later | Run the backend | [Python for Windows](https://www.python.org/downloads/windows/) |
| Node.js LTS, version 22.12 or later | Run the frontend; includes npm | [Node.js](https://nodejs.org/en/download) |
| Docker Desktop | Run PostgreSQL 17 with Docker Compose | [Windows installation](https://docs.docker.com/desktop/setup/install/windows-install/) |
| Web browser | Open the application | Edge, Chrome, or Firefox |

VS Code is optional. PostgreSQL and pgAdmin do not need to be installed separately: Docker downloads and runs the PostgreSQL version defined in the project.

Enable the option to add Python to PATH in the installer, if available. After installation, close and reopen PowerShell.

For Docker Desktop with WSL 2, follow the Windows, memory, virtualization, and WSL requirements in the [official documentation](https://docs.docker.com/desktop/setup/install/windows-install/). If WSL is not installed, open PowerShell **as administrator** and run:

```powershell
wsl --install
```

Restart Windows if prompted. Open Docker Desktop, use the WSL 2 backend, and wait for the Docker engine to start. See the [official WSL setup instructions](https://learn.microsoft.com/windows/wsl/install).

Check the installations in a new PowerShell window:

```powershell
git --version
python --version
node --version
npm.cmd --version
docker --version
docker compose version
docker info
```

`docker info` must display server information without connection errors. Node 20.17 does not meet this project's Vite requirements; install a compatible LTS version.

## 2. Download the Code from GitHub

Open PowerShell in the folder where you want to store the project:

```powershell
git clone https://github.com/DatumLex/datumlex-core.git
cd datumlex-core
```

If the repository is private, your GitHub account must have access. Alternatively, select **Code → Download ZIP**, extract the archive, and open PowerShell in the extracted folder.

The main folder contains `backend` and `frontend`. In this guide, “project root” means the `datumlex-core` folder.

## 3. Set Up the Backend

Starting from the project root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Copy `.env.example` only during the initial installation. If `.env` already exists, edit it to preserve your settings.

Fill in these two lines in `.env`, replacing `YOUR_LOCAL_PASSWORD` with the same password in both places:

```dotenv
POSTGRES_PASSWORD=YOUR_LOCAL_PASSWORD
DATABASE_URL=postgresql://datumlex:YOUR_LOCAL_PASSWORD@127.0.0.1:5433/datumlex_v2
```

Choose a long local password containing letters and numbers to simplify setup. If you use special characters, URL-encode the password inside `DATABASE_URL`. Keep the other example settings. Save and close the editor.

The `.env` file contains local configuration and should not be uploaded to GitHub. These commands use the Python executable inside `.venv` directly, without requiring virtual environment activation.

## 4. Download and Start PostgreSQL

With Docker Desktop open, run these commands in `backend`:

```powershell
docker compose up -d --wait db
docker compose ps
```

On the first run, Docker downloads `postgres:17-alpine`, creates the `datumlex_v2` database, and starts the service. The output should show that the database is running and healthy (`healthy`).

| Setting | Value |
| --- | --- |
| Host | `127.0.0.1` |
| Windows port | `5433` |
| Database name | `datumlex_v2` |
| User | `datumlex` |
| Password | The one defined in `.env` |

Data is stored in a persistent Docker volume, defined as `datumlex_pg_v2` in Compose; Docker may add a prefix to the name. Stopping the container preserves this volume.

Create the tables using Django migrations:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
```

These instructions are for a fresh **v2** database. Migration `0002_resource_schema` recreates the old model's tables and discards v1 data. Do not run it against an older database whose contents must be preserved without a backup and migration plan.

`backend/datumlex.session.sql` is a model reference. **Do not run this SQL to install the database**: the `migrate` command creates the tables.

## 5. How to Obtain the Database Data

Downloading the GitHub code and PostgreSQL image does not download another computer's data. The inspected local repository contains neither a populated database backup nor a backup download link. Migrations create an empty database.

Choose an option below. Use option A to get started quickly. To reproduce a teammate's data, request a backup as described in option B.

### Option A — Download a Sample Directly from DataJud

1. Visit the [official DataJud Public API access page](https://datajud-wiki.cnj.jus.br/api-publica/acesso/).
2. Copy the current public key provided by CNJ.
3. Open `backend/.env` and set `DATAJUD_API_KEY` to the key only, without quotation marks or the `Authorization:` or `APIKey` prefixes.

```dotenv
DATAJUD_API_KEY=PASTE_THE_KEY_HERE
```

In `backend`, run:

```powershell
.\.venv\Scripts\python.exe manage.py extract_datajud --subjects 10431,10433,10439 --start 2023-01-01 --page-size 100 --max-pages 2
```

The command queries public TJDFT documents with the specified subject codes and filing dates from January 1, 2023 through the execution date. It fetches **up to 200 documents** and may load fewer depending on availability and validation. This is a sample, not a complete copy of CNJ's database or another team member's database.

`paused` means the extraction reached the configured page limit, not that it failed. To continue, use the `Run` number shown in the terminal. Example for `Run 1`:

```powershell
.\.venv\Scripts\python.exe manage.py extract_datajud --resume 1 --max-pages 5
```

Replace `1` with the actual identifier. Run only one extraction at a time against the same database. See [the backend README](backend/README.md) for additional parameters.

### Option B — Download and Restore a Team Backup

To obtain another computer's data, a team member must export the database and share the `.dump` file through an authorized channel, such as a team storage link. **This guide does not include a backup link because none has been supplied.** Use code and a backup compatible with the v2 schema.

**If you have the populated database:** stop ongoing extractions, keep the database running, and execute these commands in `backend`:

```powershell
docker compose exec -T db pg_dump -U datumlex -d datumlex_v2 -Fc --no-owner --no-acl -f /tmp/datumlex_v2.dump
docker compose cp db:/tmp/datumlex_v2.dump ./data/datumlex_v2.dump
```

Share `backend/data/datumlex_v2.dump`. It contains the data; you do not need to share `.env` or passwords. The command writes the file inside the container before copying it, avoiding binary redirection in PowerShell.

**If you received the file:** download it to `backend/data/datumlex_v2.dump`. With the database started as described in step 4, restore it into a **new, separate database** to preserve existing contents of `datumlex_v2`:

```powershell
docker compose cp ./data/datumlex_v2.dump db:/tmp/datumlex_v2.dump
docker compose exec -T db createdb -U datumlex datumlex_restore
docker compose exec -T db pg_restore -U datumlex -d datumlex_restore --no-owner --no-acl --exit-on-error /tmp/datumlex_v2.dump
```

If `datumlex_restore` already exists, choose another new name and use it in the commands and `.env`. Do not repeat the restore against a populated database. Proceed only if the restore completes without errors.

Change only the database name in `backend/.env`, keeping your local password:

```dotenv
DATABASE_URL=postgresql://datumlex:YOUR_LOCAL_PASSWORD@127.0.0.1:5433/datumlex_restore
```

Check migration compatibility:

```powershell
.\.venv\Scripts\python.exe manage.py showmigrations
.\.venv\Scripts\python.exe manage.py check
```

The full backup includes tables and migration history. If migrations are pending, check with the team that the backup matches the code version before running `migrate`. Restart the backend after changing `.env`.

## 6. Start the Backend

In the first terminal, in `backend`:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Keep the terminal open. Visit [the health check endpoint](http://127.0.0.1:8000/api/health/). The expected response is:

```json
{"status":"ok","service":"datumlex-backend","database":"postgresql"}
```

You can also view [the statistics endpoint](http://127.0.0.1:8000/api/statistics/). An empty database can be healthy even without data for the dashboard.

## 7. Install and Start the Frontend

Open a **second PowerShell window** in the project root:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

`npm.cmd ci` installs the versions recorded in `package-lock.json`. Run it during the initial installation and when dependencies change. Using `npm.cmd` avoids PowerShell execution policy restrictions on `npm.ps1`.

Keep this terminal open and visit **[http://127.0.0.1:5173/](http://127.0.0.1:5173/)**.

Vite forwards `/api` requests to `127.0.0.1:8000`. For this local setup, you do not need a frontend `.env` file or a DataJud key in the frontend.

## 8. Start the Project on Subsequent Days

After the initial setup, open Docker Desktop and wait for it to start.

**Terminal 1 — in `backend`:**

```powershell
docker compose up -d --wait db
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

**Terminal 2 — in `frontend`:**

```powershell
npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open [the dashboard](http://127.0.0.1:5173/). You do not need to recreate `.venv`, copy `.env`, restore the backup, or download data again each time.

To stop, press `Ctrl+C` in each terminal. To stop the database as well, run this in `backend`:

```powershell
docker compose stop db
```

Do not use `docker compose down -v` to finish your session: `-v` removes volumes and may delete local data.

## 9. Common Issues

| Issue | What to Check |
| --- | --- |
| `python`, `git`, `node`, or `npm` is not recognized | Verify the installation and PATH; open a new terminal. |
| Vite reports an unsupported Node version | Install a compatible Node LTS version, 22.12 or later, and check `node --version`. |
| Docker cannot connect and mentions a pipe or daemon | Open Docker Desktop and wait for the engine to start; run `docker info`. |
| Docker exits with a `sailor-ingest.sock` error | This is a Docker failure before the database starts. Restart Windows and follow the [official troubleshooting procedures](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/). Avoid a factory reset without backing up volumes. |
| Port `5433` is in use | Check `docker ps`. Another PostgreSQL container may use the same port; stop only the service identified as conflicting. |
| PostgreSQL authentication fails | Check that the password in `DATABASE_URL` matches the password used when the volume was created. Changing `POSTGRES_PASSWORD` in `.env` does not change an existing database's password. |
| Port `8000` or `5173` is in use | Check whether the project is running in another terminal. Stop the previous instance before starting another one. |
| The frontend opens but displays a loading error | Check that the backend responds at `/api/health/` and that the database is healthy. |
| The dashboard has no records | Creating tables does not import data; follow option A or B in step 5. |
| DataJud returns an API key error | Update `DATAJUD_API_KEY` with the current public key and run the extraction again. |

To check database status and logs, run these commands in `backend`:

```powershell
docker compose ps
docker compose logs --tail 80 db
```

## 10. Final Checklist

- PostgreSQL is running and healthy in Docker.
- The backend returns `status: ok` at `http://127.0.0.1:8000/api/health/`.
- The frontend is available at `http://127.0.0.1:5173/`.
- Data has been loaded from DataJud or a backup if you want to view records.

This procedure is intended for local development. For schema details and guidance on interpreting the data, see [the v2 schema](backend/docs/resource-schema.md) and [the methodology](backend/docs/merit-methodology.md).
