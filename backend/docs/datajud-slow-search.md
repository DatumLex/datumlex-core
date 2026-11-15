# Slow and overloaded DataJud searches

The collector must distinguish a local HTTP read timeout from an incomplete
Elasticsearch search returned with HTTP 200. In the observed failure, the CNJ
server reported `es_rejected_execution_exception` with its search queue full.
Partial hits from that response are not a complete page and must not be loaded.

The read timeout now defaults to 120 seconds. Set `DATAJUD_HTTP_TIMEOUT` in the
local environment to override it, up to 300 seconds. An explicit constructor
timeout still takes precedence. This setting does not bypass access controls
or guarantee upstream availability.

Search timeouts and shard rejections caused specifically by
`es_rejected_execution_exception` receive bounded retries with 10, 20, and
30-second waits. Each retry sends the identical request/cursor. Non-transient
shard failures are rejected immediately. The page and its cursor are committed
together only after a complete search is returned and the records are validated.

When retries are exhausted, the extraction is failed with its saved cursor
preserved. Resume it using its real run ID:

```powershell
.venv\Scripts\python.exe manage.py extract_datajud --resume RUN_ID --max-pages 1
```

The manual history helper uses the same configured timeout for its readiness
probe; a 15-second probe must not label a service unavailable merely because
it responds after that interval. Historical coverage is established by saved
records and source reports, not by requesting a broad date range alone.

Tests: `tests.test_datajud_timeout`, `tests.test_pipeline`, `tests.test_stj`.
