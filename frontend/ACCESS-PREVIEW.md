# Access management

The original in-memory preview has been replaced by Django authentication and persisted access management. Demo profiles and sample users are no longer loaded. See [backend access control](../backend/docs/access-control.md) for deployment, support policy, and tests.

Start Django on port 8000 and Vite using `npm run dev`. Login with a provisioned account, or register and wait for approval. Support uses `suport` and its deployment-configured password, which is never included in frontend assets. Ordinary users login with email or CPF.

Validation: `npm run lint`, `npm run build`, and `tests/access-live.mjs` against the real local API. The historical dashboard integration script predates the authentication boundary.
