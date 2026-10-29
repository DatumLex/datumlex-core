"""Authenticated client for the official PDPJ-Br BNP/Pangea integration API."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from src.api.pangea_scope import canonical_court, selected_courts, source_organs


class PangeaError(Exception):
    pass


class PangeaClient:
    def __init__(self, timeout=45):
        self.base_url = settings.BNP_API_BASE_URL.rstrip("/")
        self.token_url = settings.BNP_TOKEN_URL
        self.client_id = settings.BNP_API_CLIENT_ID
        self.client_secret = settings.BNP_API_CLIENT_SECRET
        self.timeout = timeout
        self._access_token = None
        if not self.client_id or not self.client_secret:
            raise PangeaError(
                "Configure BNP_API_CLIENT_ID and BNP_API_CLIENT_SECRET in backend/.env. "
                "The official BNP/Pangea API uses PDPJ-Br client credentials."
            )

    @staticmethod
    def _read_json(request, timeout, capture=None):
        try:
            with urlopen(request, timeout=timeout) as response:
                raw=response.read(20_000_001)
                if len(raw)>20_000_000:
                    raise ValueError('Response exceeds bounded 20 MB')
                payload=json.loads(raw)
                if capture is not None:
                    capture(raw)
                return payload
        except HTTPError as exc:
            # Keycloak exposes a useful OAuth error code; never log its body,
            # which may contain provider details beyond the sanitized code.
            try:
                payload = json.loads(exc.read())
                error_code = payload.get("error", "") if isinstance(payload, dict) else ""
                error_code = re.sub(r"[^A-Za-z0-9_.-]", "", str(error_code))[:64]
            except (ValueError, OSError):
                error_code = ""
            suffix = f" ({error_code})" if error_code else ""
            raise PangeaError(f"BNP/Pangea HTTP {exc.code}{suffix}.") from None
        except (URLError, TimeoutError, OSError):
            raise PangeaError("BNP/Pangea indisponível ou conexão interrompida.") from None
        except (ValueError, TypeError):
            raise PangeaError("BNP/Pangea retornou JSON inválido.") from None

    def _token(self):
        if self._access_token:
            return self._access_token
        request = Request(
            self.token_url,
            data=urlencode({
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            }).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        token_payload = self._read_json(request, self.timeout)
        token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
        if not token:
            raise PangeaError("O SSO da PDPJ-Br não retornou access_token.")
        self._access_token = token
        return token

    def get_page(self, resource, page_number, page_size):
        if resource != "recurso-repetitivo":
            raise PangeaError("Tipo de precedente BNP ainda não habilitado neste conector.")
        query = urlencode({"pageNumber": page_number, "pageSize": page_size})
        request = Request(
            f"{self.base_url}/v1/{resource}?{query}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token()}",
                "User-Agent": "DatumLex-BNP-connector/1.0",
            },
        )
        result = self._read_json(request, self.timeout)
        if not isinstance(result, (dict, list)):
            raise PangeaError("BNP/Pangea retornou estrutura de página inesperada.")
        return result


class PangeaPublicSearchClient:
    """Public Pangea frontend search API for the explicitly selected local courts."""

    def __init__(self, timeout=45):
        self.base_url = settings.PANGEA_SEARCH_BASE_URL.rstrip("/")
        self.timeout = timeout
        self._catalog = None
        self.last_response_bytes = None

    def _get_json(self, url):
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "DatumLex-Pangea-Connector/1.0"},
        )
        return PangeaClient._read_json(request, self.timeout)

    def get_catalog(self):
        catalog = self._get_json(f"{self.base_url}/api/v1/parametros")
        if not isinstance(catalog, dict):
            raise PangeaError("Pangea retornou catálogo em formato inesperado.")
        for field in ("orgaos", "especies"):
            entries = catalog.get(field)
            if not isinstance(entries, list) or not entries:
                raise PangeaError(f"Catálogo Pangea vazio ou inválido: {field}.")
            if any(not isinstance(item, dict) or not item.get("sigla") for item in entries):
                raise PangeaError(f"Catálogo Pangea sem sigla válida: {field}.")
        self._catalog = catalog
        return catalog

    def search_page(self, query, page_index, page_size, courts=None):
        if not isinstance(query, str) or not query.strip():
            raise PangeaError("Informe o termo de pesquisa do Pangea.")
        if page_index < 0 or not 1 <= page_size <= 100:
            raise PangeaError("Pangea requer página zero-based >= 0 e tamanho entre 1 e 100.")
        catalog = self._catalog or self.get_catalog()
        try:
            selected = selected_courts(courts)
            organs = source_organs(selected, catalog)
        except ValueError as exc:
            raise PangeaError(str(exc)) from exc
        filter_data = {
            "buscaGeral": query.strip(),
            "todasPalavras": "",
            "quaisquerPalavras": "",
            "semPalavras": "",
            "trechoExato": "",
            "atualizacaoDesde": "",
            "atualizacaoAte": "",
            "nr": "",
            "orgaos": organs,
            "tipos": [str(item["sigla"]) for item in catalog["especies"]],
            "cancelados": False,
            "ordenacao": "Text",
            "pagina": page_index + 1,
            "tamanhoPagina": page_size,
        }
        payload = json.dumps({"filtro": filter_data}, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/v1/precedentes",
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "DatumLex-Pangea-Connector/1.0",
            },
            method="POST",
        )
        result = PangeaClient._read_json(request, self.timeout, capture=lambda raw: setattr(self,'last_response_bytes',raw))
        if not isinstance(result, dict):
            raise PangeaError("Pangea retornou página em formato inesperado.")
        rows, total = result.get("resultados"), result.get("total")
        if (
            not isinstance(rows, list)
            or isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
            or len(rows) > page_size
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise PangeaError("Pangea retornou resultados ou total inválido.")
        if any(canonical_court(row.get("orgao")) not in selected for row in rows):
            raise PangeaError("Pangea retornou tribunal fora do filtro solicitado.")
        return result
