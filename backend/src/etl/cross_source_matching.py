"""Conservative exact-identifier reconciliation for sourced STJ citations."""

import re

MATCHER_VERSION = "exact-cnj-citation-v1"


def normalize_cnj_identifier(value):
    """Return a CNJ identifier only when all 20 digits are explicitly present."""
    if not isinstance(value, str):
        return ""
    digits = re.sub(r"\D", "", value)
    return digits if len(digits) == 20 else ""


def candidate_key(reference_id, cited_identifier, local_decision_id=""):
    import hashlib

    identity = "\x1f".join(
        (str(reference_id), cited_identifier.strip(), str(local_decision_id), MATCHER_VERSION)
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
