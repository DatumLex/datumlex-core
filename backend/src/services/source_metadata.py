"""Allowlisted public metadata extraction for approved legal sources.

Exposes only curated bibliographic, court, TPU and licensing metadata without
leaking internal archive provenance, NLP fields, permissions or full text.
"""

from urllib.parse import urlparse

from src.nlp.topics import TOPICS

TOPIC_LABELS = {key: label for key, label, _ in TOPICS}
GENERAL_TOPIC_LABELS = {
    "responsabilidade-civil": "Responsabilidade civil (escopo geral)",
}
VERIFIED_TPU_LABELS = {
    "verified_official_code": "TPU oficial da ficha",
    "verified_official_label": "TPU mapeada do rótulo oficial",
    "verified_linked_datajud": "TPU derivada do cadastro DataJud vinculado",
}


def _clean_str(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_year(value):
    return value if type(value) is int and 1900 <= value <= 2100 else None


def _safe_license_url(evidence, safe_url):
    if not isinstance(evidence, list):
        return None
    for candidate in evidence:
        url = safe_url(candidate)
        if not url:
            continue
        host = (urlparse(url).hostname or "").lower()
        if host == "creativecommons.org" or host.endswith(".creativecommons.org"):
            return url
    return None


def _license_version_note(license_name, rights):
    explicit = _clean_str(rights.get("version_note"))
    if explicit:
        return explicit
    conditions = _clean_str(rights.get("conditions")) or ""
    lowered = conditions.lower()
    if not lowered:
        return None
    has_other_version = (
        ("4.0" in license_name and "3.0" in lowered)
        or ("3.0" in license_name and "4.0" in lowered)
        or ("fascículo" in lowered and ("3.0" in lowered or "4.0" in lowered))
    )
    if has_other_version:
        return (
            "Há divergência entre a versão da licença indicada na edição individual e no "
            "catálogo do fascículo; confirme a edição de referência antes de reutilizar."
        )
    return None


def extract_tpu(metadata):
    tpu = metadata.get("tpu")
    if not isinstance(tpu, dict):
        return None, []
    state = _clean_str(tpu.get("state"))
    raw_codes = tpu.get("codes")
    codes = (
        [code for code in raw_codes if type(code) is int and code > 0]
        if isinstance(raw_codes, list)
        else []
    )
    official_codes = codes if state == "verified_official_code" else []
    if state in VERIFIED_TPU_LABELS and codes:
        return {
            "state": state,
            "codes": codes,
            "label": VERIFIED_TPU_LABELS[state],
        }, official_codes
    return None, official_codes


def extract_bibliography(metadata, *, category):
    raw = metadata.get("bibliography")
    bib = raw if isinstance(raw, dict) else {}
    fields = {}
    for key in ("publication", "publisher", "place", "edition", "pages", "period"):
        val = _clean_str(bib.get(key))
        if val:
            fields[key] = val
    for key in ("volume", "issue"):
        val = bib.get(key)
        if type(val) is int and val > 0:
            fields[key] = val
        elif isinstance(val, str) and val.strip():
            fields[key] = val.strip()
    year = _clean_year(bib.get("year")) or _clean_year(metadata.get("year"))
    if year is not None and (fields or category == "doctrine"):
        fields["year"] = year
    if category == "doctrine":
        locator = _clean_str(metadata.get("source_locator"))
        if locator:
            fields["locator"] = locator
    return fields or None


def extract_license(metadata, *, authors, origin, bibliography, safe_url):
    rights = metadata.get("rights")
    if not isinstance(rights, dict):
        return None
    name = _clean_str(rights.get("license"))
    if not name:
        return None
    parts = []
    clean_authors = [a.strip() for a in (authors or []) if isinstance(a, str) and a.strip()]
    if clean_authors:
        parts.append(", ".join(clean_authors))
    publisher = (bibliography or {}).get("publisher") or _clean_str(metadata.get("issuer")) or _clean_str(origin)
    if publisher:
        parts.append(publisher)
    publication = (bibliography or {}).get("publication")
    if publication:
        parts.append(publication)
    return {
        "name": name,
        "attribution": " · ".join(parts) if parts else None,
        "url": _safe_license_url(rights.get("evidence"), safe_url),
        "version_note": _license_version_note(name, rights),
    }


def extract_topics(metadata):
    raw = metadata.get("topics")
    if not isinstance(raw, list):
        return []
    labels = []
    for code in raw:
        label = TOPIC_LABELS.get(code) or GENERAL_TOPIC_LABELS.get(code)
        if label and label not in labels:
            labels.append(label)
    return labels


def public_source_metadata(provenance, *, category, authors=(), origin="", safe_url):
    metadata = provenance.get("metadata") if isinstance(provenance, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    authority = metadata.get("authority") if isinstance(metadata.get("authority"), dict) else {}
    rights = metadata.get("rights") if isinstance(metadata.get("rights"), dict) else {}
    tpu_info, official_tpu = extract_tpu(metadata)
    bibliography = extract_bibliography(metadata, category=category)
    license_info = extract_license(
        metadata,
        authors=authors,
        origin=origin,
        bibliography=bibliography,
        safe_url=safe_url,
    )
    publication_year = (bibliography or {}).get("year") or _clean_year(metadata.get("year"))
    publication_period = (bibliography or {}).get("period")
    case_number = None if rights.get("hide_case_number") else _clean_str(metadata.get("case_number"))
    return {
        "identifier": _clean_str(metadata.get("id")),
        "judging_body": _clean_str(metadata.get("judging_body")),
        "case_number": case_number,
        "reference_number": _clean_str(metadata.get("reference_number")),
        "official_status": _clean_str(authority.get("official_status")),
        "verified_on": _clean_str(metadata.get("verified_on")),
        "topics": extract_topics(metadata),
        "official_tpu": official_tpu,
        "tpu": tpu_info,
        "publication_year": publication_year,
        "publication_period": publication_period,
        "bibliography": bibliography,
        "license": license_info,
    }
