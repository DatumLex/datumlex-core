"""Bounded retries and strict search_after pagination for the official TJDFT API."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = "https://api-publica.datajud.cnj.jus.br/api_publica_tjdft/_search"
SOURCE_FIELDS = [
    "id",
    "numeroProcesso",
    "tribunal",
    "grau",
    "nivelSigilo",
    "classe",
    "orgaoJulgador",
    "assuntos",
    "dataAjuizamento",
    "dataHoraUltimaAtualizacao",
    "@timestamp",
    "movimentos",
]


class DataJudError(Exception):
    pass


class DataJudClient:
    def __init__(self, api_key, timeout=45, attempts=4, pause=0.5):
        if not api_key.strip():
            raise DataJudError("Configure DATAJUD_API_KEY using the current CNJ public key.")
        self.api_key = api_key.strip().removeprefix("APIKey ")
        self.timeout, self.attempts, self.pause = timeout, attempts, pause

    def search(self, scope, cursor=None):
        body = {
            "size": scope["page_size"],
            "track_total_hits": True,
            "_source": SOURCE_FIELDS,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"nivelSigilo": 0}},
                        {"terms": {"assuntos.codigo": scope["subject_codes"]}},
                        {
                            "bool": {
                                "minimum_should_match": 1,
                                "should": [
                                    {
                                        "range": {
                                            "dataAjuizamento": {
                                                "gte": scope["start"] + "T00:00:00Z",
                                                "lt": scope["end_exclusive"] + "T00:00:00Z",
                                            }
                                        }
                                    },
                                    # Observed TJDFT 2026 source: yyyyMMddHHmmss indexed as epoch_millis.
                                    # Match both encodings; normalize and recheck the real date before loading.
                                    {
                                        "range": {
                                            "dataAjuizamento": {
                                                "gte": int(scope["start"].replace("-", "") + "000000"),
                                                "lt": int(scope["end_exclusive"].replace("-", "") + "000000"),
                                            }
                                        }
                                    },
                                ],
                            }
                        },
                    ]
                }
            },
            "sort": [{"@timestamp": "asc"}, {"id.keyword": "asc"}],
        }
        if cursor is not None:
            body["search_after"] = cursor
        request = Request(
            ENDPOINT,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "APIKey " + self.api_key,
                "User-Agent": "DatumLex-local-research/0.1",
            },
        )
        for attempt in range(self.attempts):
            retry_after = None
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    result = json.load(response)
                if result.get("timed_out") or result.get("_shards", {}).get("failed", 0):
                    raise DataJudError("DataJud returned an incomplete search; page was not loaded.")
                if not isinstance(result.get("hits", {}).get("hits"), list):
                    raise DataJudError("Unexpected DataJud response schema.")
                hits = result["hits"]["hits"]
                if hits and (
                    not hits[-1].get("sort")
                    or hits[-1]["sort"] == cursor
                    or len(hits[-1]["sort"]) != 2
                    or any(v is None for v in hits[-1]["sort"])
                ):
                    raise DataJudError("Pagination cursor missing or not advancing.")
                time.sleep(self.pause)
                return result["hits"]
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise DataJudError(
                        f"DataJud HTTP {exc.code}; check access and query configuration."
                    ) from None
                retry_after = exc.headers.get("Retry-After")
            except (URLError, TimeoutError, OSError):
                pass
            except (ValueError, TypeError):
                raise DataJudError("DataJud returned invalid JSON.") from None
            if attempt + 1 < self.attempts:
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(min(delay, 30))
        raise DataJudError("DataJud unavailable after bounded retries; resume the saved run later.")
