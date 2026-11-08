# Extraction automation after cloning

Run these commands in PowerShell from the project root on Windows. Each clone
keeps its configuration, Python environment, data, cursors, and logs locally.
Install Git and Python 3.12 or later first. Node.js is required when installing
the frontend. PostgreSQL is optional for the first local run.

If PowerShell blocks local scripts, open a shell for this installation with
`powershell -NoProfile -ExecutionPolicy RemoteSigned`. Organization policies
can require a different execution procedure.

## Step 1: check the prerequisites

Open Windows PowerShell and verify the installed tools:

```powershell
git --version
py -3 --version
```

Python must be 3.12 or later. If the Python launcher is unavailable, use
`python --version`; setup also supports that executable. Internet access is
needed to install dependencies and collect public source material.

## Step 2: clone and prepare a new installation

```powershell
git clone https://github.com/DatumLex/datumlex-core.git
cd datumlex-core

# Prepare the extraction backend and its persistent SQLite database.
.\scripts\setup.ps1 -BackendOnly -Migrate
```

Setup creates an ignored `backend/.env` with generated local secrets, installs
the backend requirements, applies migrations, and registers the court catalog.
It preserves an existing configuration. To install frontend dependencies as
well, omit `-BackendOnly`.

The default ETL sources use public interfaces and need no DataJud key.
`DATAJUD_API_KEY` is required for the separate DataJud commands. Credentials,
downloaded documents, and database contents are excluded from Git.

## Step 3: review the database and credentials

Open the configuration created by setup:

```powershell
notepad .\backend\.env
```

For the simplest local installation, leave `DATABASE_URL=` empty. Setup uses
the persistent SQLite file at `backend/data/datumlex_v2.sqlite3`; Docker is
not required. Keep the generated `DJANGO_SECRET_KEY` and
`DATUMLEX_SUPPORT_PASSWORD` private. Do not commit this file.

The scheduled source list below uses public interfaces. Leave DataJud and
BNP integration credentials empty unless enabling their separate integrations.
The public Pangea search source does not require those BNP credentials.

For PostgreSQL instead, edit `backend/.env` before migrating that database. Set `POSTGRES_PASSWORD`
and a matching `DATABASE_URL` using a URL-encoded password and loopback host.
Then start Docker Desktop and run:

```powershell
docker compose --project-directory backend -f backend/compose.yaml up -d
.\scripts\setup.ps1 -BackendOnly -Migrate -SkipDependencies
```

An existing PostgreSQL volume keeps its previous password. The automation
connects to the configured database and preserves its existing records.
Choosing PostgreSQL after the SQLite quick start creates a separate database;
it does not copy existing SQLite records. Use the matching database settings
for subsequent manual and scheduled runs.

## Step 4: run and inspect a first bounded cycle

```powershell
# Start small and include collection, NLP, import, and coverage.
.\scripts\run-etl.ps1 -Once -BatchSize 25 -DoctrineLimit 1

# View the outcome and the log locations.
.\scripts\status.ps1
```

The runner checks the configuration, database connection, migration state,
and storage before starting. A nonzero exit means the cycle needs attention.
The stage logs identify which source or processing step failed.
Confirm that status reports setup as `ready` and the complete-cycle state as
`completed` before enabling the schedule. A completed cycle can contain no new
eligible records; inspect coverage and source logs to understand its results.

The default sources are `doctrine,pangea,tjdft,ementas,djen`. For example:

```powershell
.\scripts\run-etl.ps1 -Once -Sources 'tjdft,pangea' -BatchSize 100
.\scripts\run-etl.ps1 -Mode process -Once -Sources 'doctrine,pangea'
```

The second command processes archived reference material. Source failures are
recorded independently, and valid archived inputs remain available to the
processor. Each cycle preserves source artifacts, hashes, pending-page cursors,
and versioned NLP evidence.

`BatchSize` applies to TJDFT and must be a multiple of 25 between 25 and 1,000.
`Target` defaults to 20,000 unique TJDFT full-text documents. Other source
limits are described in [the ETL guide](ETL-ELT-LOCAL.md). Actual additions
depend on duplicates, source availability, and eligibility.

## Step 5: choose and preview the daily configuration

After a successful manual cycle, preview the scheduled action:

```powershell
.\scripts\install-schedule.ps1 -At '19:40' -BatchSize 100 -DoctrineLimit 1 -Sources 'doctrine,pangea,tjdft,ementas,djen' -WhatIf
```

`At` is the daily Windows local time. `Sources` chooses collectors, `BatchSize`
sets the TJDFT batch, and `DoctrineLimit` limits the doctrine collector. These
values are stored in the scheduled action; editing the command later requires
running the installer again. Preview does not register or execute a task.

## Step 6: activate the schedule

Install it using the same parameters, removing `-WhatIf`:

```powershell
.\scripts\install-schedule.ps1 -At '19:40' -BatchSize 100 -DoctrineLimit 1 -Sources 'doctrine,pangea,tjdft,ementas,djen'
.\scripts\status.ps1
```

Use `-RunNow` to also start the installed task immediately. The installer
accepts `Sources`, `Target`, and `DoctrineLimit`, matching the manual runner.
Without `-RunNow`, installation enables future runs without starting a cycle.

The task name is derived from the clone path. Reinstalling updates that
clone's task. A custom `TaskName` is accepted only when it is free or already
belongs to the same installation.

Every scheduled execution runs the clone's `scripts/run-etl.ps1 -Mode all -Once`
through Windows PowerShell. The saved action uses absolute paths and an explicit
working directory, with a process-local RemoteSigned execution policy.
The task runs under the current user's interactive session,
uses the Windows time zone, and resumes a missed time when available. Keep the
computer powered, the user signed in, and the required network and database
services available. Its execution limit is six hours.

Task Scheduler prevents overlapping instances of the same task. The ETL's
existing role and source locks also guard the same clone's files.

## Step 7: monitor, change, or stop the automation

Run `.\scripts\status.ps1` after the first scheduled time and inspect the
task's last result, next run, ETL state, and log paths. You can also open
Windows Task Scheduler with `taskschd.msc` and locate the printed task name.
To change the time, sources, or batch size, repeat step 6 with the new values.

To pause or remove a schedule, replace the example placeholder below with
the exact task name printed by status:

```powershell
Disable-ScheduledTask -TaskName 'DatumLex-Local-<clone-hash>'
# Re-enable later.
Enable-ScheduledTask -TaskName 'DatumLex-Local-<clone-hash>'
# Remove the schedule when retiring this installation.
Unregister-ScheduledTask -TaskName 'DatumLex-Local-<clone-hash>' -Confirm:$false
```

After moving a clone, disable its old task and reinstall from the new path.

## Step 8: diagnose a failed cycle

- `backend/data/operations/etl-all.json` records the last complete-cycle state.
- `etl-collect.json` and `etl-process.json` record separate worker modes.
- `etl-logs/<job>/` stores each stage's output and error log.
- `preflight-logs/` records setup and database checks, including failures before collection.
- `collection-coverage.json` reports the observed TJDFT and Pangea collection.
- `nlp-local/jobs/<job>/` preserves the queue and NLP processing results.

For a missing database or pending migrations, rerun
`scripts/setup.ps1 -Migrate -SkipDependencies`. For PostgreSQL connection
errors, start the database service and verify the local configuration. After
fixing a source or network problem, repeat the bounded cycle to resume work.

The schedule prepares candidate evidence with its source and review state.
Legal review and release evaluation are separate project tasks.
Use a single scheduled installation for each database.
