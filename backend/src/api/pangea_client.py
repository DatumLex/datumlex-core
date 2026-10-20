"""Authenticated client for the official PDPJ-Br BNP/Pangea integration API."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings


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
    def _read_json(request, timeout):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            raise PangeaError(f"BNP/Pangea HTTP {exc.code}.") from None
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
