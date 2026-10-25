# Why DatumLex Uses Render

**Decision date:** October 24, 2026  
**Status:** Adopted for the current academic deployment and initial validation phase

## Decision

DatumLex uses Render because it accommodates the project's existing React frontend, Django backend, and PostgreSQL database within a single hosting platform. This lets the team publish a working application with limited infrastructure administration and continue using its existing GitHub development workflow.

The decision prioritizes compatibility, straightforward deployment, and low initial cost. The current free configuration is a temporary demonstration environment; operating a dependable production service will require upgrading the relevant resources and strengthening operational controls.

## Project Requirements

DatumLex is a legal analytics web application. Its infrastructure must support:

- A React/Vite interface that users can access through a browser.
- A Django API with session-based authentication, permissions, and CSRF protection.
- A PostgreSQL database for judicial records, precedents, ingestion provenance, and user accounts.
- Deployment from the `DatumLex/datumlex-core` GitHub repository.
- Data ingestion from DataJud, Pangea, and official STJ publications.

The team also needs an environment that is practical to maintain during an academic project, without adding a large infrastructure workload.

## Reasons for Choosing Render

| Reason | Relevance to DatumLex |
|---|---|
| **Compatibility with the existing architecture** | Render supports Django web services and PostgreSQL, allowing the backend to retain its current framework and relational data model. The frontend is deployed separately as a static site. |
| **GitHub integration** | The application can be rebuilt and deployed when changes reach the linked branch. This fits the team's pull request and merge workflow. |
| **Centralized operational visibility** | The team can inspect deployment history and service logs through the Render dashboard, making deployment failures easier to investigate. |
| **Database connectivity** | Render provides an internal PostgreSQL connection address. The API and database are deployed in the same region, enabling their communication over the platform's private network. |
| **Low-cost initial validation** | Free web service, database, and static hosting options allow the team to demonstrate and validate the application before committing to paid infrastructure. |

These capabilities are documented in Render's guides for [Django deployment](https://render.com/docs/deploy-django), [deployments and Git integration](https://render.com/docs/deploys), [private networking](https://render.com/docs/private-network), and [free services](https://render.com/docs/free).

## Current Implementation

| Component | Deployment |
|---|---|
| Frontend | React/Vite static site: `datumlex-demo-web` |
| Backend | Django web service running with Gunicorn: `datumlex-demo-api` |
| Database | Render PostgreSQL 17: `datumlex-demo-db` |
| Repository | `DatumLex/datumlex-core`, branch `main` |
| Application URL | <https://datumlex-demo-web.onrender.com/> |

Both application services are connected to GitHub and use **On Commit** automatic deployment. Their root directories are configured separately: `frontend/` and `backend/`.

The backend uses environment variables for its database connection and application secrets. Authentication and user approval remain responsibilities of the Django application; Render supplies the hosting environment.

Database migrations run as part of the current backend build command because the selected free service does not support a pre-deploy command. This is an initial deployment arrangement. Before production, migration execution should be reviewed and moved into a controlled release process supported by the chosen plan.

Data ingestion is a separate operational process. The current ETL runs on the team's Windows computer and writes to Render PostgreSQL through a TLS connection restricted to that computer's authorized public IP. Code deployment does not automatically refresh judicial data. The application remains hosted when that computer is off, but local ingestion cannot run then.

## Limitations and Their Impact

The free tier has constraints that directly affect this decision:

- **Idle shutdown:** a free web service sleeps after 15 minutes without inbound traffic, which can delay the next request.
- **Temporary database:** free PostgreSQL has a 1 GB capacity and expires after 30 days. The current database dashboard shows an expiration date of **November 23, 2026**.
- **Backup limitations:** free PostgreSQL does not include managed backups. The migration included a private local backup, which does not replace an ongoing backup and recovery policy.
- **Ephemeral service storage:** files written to a free web service are not durable. Judicial text files therefore need a deliberate storage solution before they can be reliably served from the hosted application.
- **Local ingestion dependency:** the current collection process depends on the computer, Docker, internet connectivity, the Windows user session, and the authorized source IP remaining available.

The platform-specific restrictions are described in [Render's free-tier documentation](https://render.com/docs/free). They mean that the current deployment is suitable for demonstration and controlled evaluation, with a planned transition to durable infrastructure before continued production use.

## Path to Production

Before relying on DatumLex as a continuous service, the team should:

1. Upgrade the database before expiration and establish tested backup and recovery procedures.
2. Select backend capacity based on measured workload, response times, and database usage.
3. Move scheduled ETL execution to an appropriate cloud job or worker so collection no longer depends on a personal computer.
4. Provide durable storage for judicial text files that the hosted application needs to access.
5. Establish automated checks and a separate homologation environment before requiring CI-approved releases to production.

Render supports deployment after CI checks pass. The current services use **On Commit**; a CI-gated deployment process is a subsequent improvement, not a capability already enforced in this installation. See [Render's deployment documentation](https://render.com/docs/deploys).

## Justification

Render is a practical fit for DatumLex's current stage because it supports the existing stack, integrates application delivery with GitHub, and reduces the infrastructure work needed to make the system accessible to the team and stakeholders. Its free tier enables initial validation, while paid services provide a path for continued operation. The decision remains appropriate as long as the team treats the free deployment as temporary and plans for durable data storage, reliable ingestion, and release validation.
