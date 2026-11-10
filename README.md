# DatumLex Core

DatumLex Core contains the frontend and backend applications for the legal
appeal analytics platform.

## Academic delivery calendar — second semester 2026

The official academic calendar supplied on October 14 sets these inclusive
execution windows and delivery deadlines:

| Sprint | Execution | Delivery | Review / Planning |
|---|---|---|---|
| 1 | September 7–27 | September 27 | September 28–October 2 |
| 2 | October 5–25 | October 25 | October 26–30 |
| 3 | November 2–22 | November 22 | November 23–27 (Review) |

The Solutions Fair is **December 3**, TG presentations are **December 7–11**,
and classes end on **December 14**. Review weeks do not extend delivery deadlines.

See the [full calendar and roadmap](https://github.com/DatumLex/documentation/blob/main/product/product-roadmap.md#academic-calendar),
[Sprint 2 delivery plan](https://github.com/DatumLex/documentation/blob/main/agile/sprint-2-plan.md),
and [GitHub Project](https://github.com/orgs/DatumLex/projects/1).
Sprint dates describe the planned delivery window; task execution dates and
completion evidence remain separate.

## Local Installation and Setup

See the [step-by-step installation guide](INSTALLATION-GUIDE.md) to install prerequisites, run the backend and frontend, and load the database data.

## Extraction automation on Windows

After cloning, run these commands from the project root with Python 3.12 or later:

```powershell
.\scripts\setup.ps1 -BackendOnly -Migrate
.\scripts\run-etl.ps1 -Once -BatchSize 25 -DoctrineLimit 1
.\scripts\status.ps1
```

After a successful manual run, enable a daily cycle with
`scripts/install-schedule.ps1 -At '19:40'`.
See [the clone automation guide](docs/operations/AUTOMACAO-LOCAL.md) for
PostgreSQL configuration, source selection, schedule previews, and recovery.
The [NLP validation tools](tools/nlp_validation/README.md) keep review samples
and quality evaluation separate from the collected corpus.

For a shareable Portuguese walkthrough covering installation, application access,
database configuration, and scheduling, see the
[team setup PDF](documentation/DatumLex-Guia-de-Configuracao-e-Automacao.pdf).
The PDF records the implementation's pre-publication status at its issue date;
use the merged code and this README to confirm current availability.

## Project structure

- `frontend/` — React dashboard application.
- `backend/` — API and data integration services.


Fluxo local de coleta e processamento desacoplados: [ETL/ELT local](docs/operations/ETL-ELT-LOCAL.md). Use `scripts/run-etl.ps1`; os originais sao preservados antes da importacao.
