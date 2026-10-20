"""HTTPS deployment behind the private Caddy proxy; backend has no published port."""

from .settings import *  # noqa: F403

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
