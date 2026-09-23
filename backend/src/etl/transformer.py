"""Normalize public metadata without inferring legal outcomes from instance presence."""

import hashlib
import json
import re
from datetime import datetime, timezone


class InvalidRecord(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def timestamp(value, required=False):
    if value in (None, ""):
        if required:
            raise InvalidRecord("Missing filing date")
        return None
    try:
        text = str(value)
        parsed = (
            datetime.strptime(text, "%Y%m%d%H%M%S")
            if re.fullmatch(r"\d{14}", text)
            else datetime.fromisoformat(text.replace("Z", "+00:00"))
        )
        return (
            parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        )
    except (ValueError, TypeError):
        raise InvalidRecord("Invalid source timestamp") from None


def flatten(values):
    if isinstance(values, dict):
        yield values
    elif isinstance(values, list):
        for value in values:
            yield from flatten(value)


def positive_code(value):
    if isinstance(value, bool):
        raise InvalidRecord("Invalid classification code")
    try:
        code = int(value)
        if code < 1 or str(code) != str(value):
            raise ValueError
        return code
    except (TypeError, ValueError):
        raise InvalidRecord("Missing or invalid classification code") from None


def normalize(hit, scope):
    source = hit.get("_source")
    if not isinstance(source, dict):
        raise InvalidRecord("Missing source payload")
    if source.get("tribunal") != "TJDFT" or source.get("nivelSigilo") != 0:
        raise InvalidRecord("Outside public TJDFT scope")
    identity = hit.get("_id") or source.get("id")
    number = source.get("numeroProcesso")
    if not identity or len(str(identity)) > 255:
        raise InvalidRecord("Missing or oversized source identifier")
    if not isinstance(number, str) or not re.fullmatch(r"\d{20}", number):
        raise InvalidRecord("Process number must be a 20-digit string")
    filing = timestamp(source.get("dataAjuizamento"), required=True)
    if not scope["start"] <= filing.date().isoformat() < scope["end_exclusive"]:
        raise InvalidRecord("Filing date outside extraction scope")
    subjects = {}
    for item in flatten(source.get("assuntos")):
        code = positive_code(item.get("codigo"))
        subjects[code] = str(item.get("nome") or "")[:255]
    if not set(subjects).intersection(scope["subject_codes"]):
        raise InvalidRecord("No matching explicit subject code")
    process_class, org = source.get("classe") or {}, source.get("orgaoJulgador") or {}
    class_code, org_code = positive_code(process_class.get("codigo")), positive_code(org.get("codigo"))
    degree = source.get("grau")
    if degree not in {"G1", "G2", "JE", "TR", "SUP"}:
        raise InvalidRecord("Missing or unsupported degree")
    movements = {}
    for item in flatten(source.get("movimentos", [])):
        code = positive_code(item["codigo"]) if item.get("codigo") is not None else None
        occurred = timestamp(item.get("dataHora"))
        complements = list(flatten(item.get("complementosTabelados", [])))
        entry = {
            "code": code,
            "name": str(item.get("nome") or "")[:512],
            "occurred_at": occurred,
            "complements": complements,
        }
        fingerprint = digest({**entry, "occurred_at": occurred.isoformat() if occurred else None})
        movements[fingerprint] = entry
    # Only allowlisted metadata is retained, including when importing an external JSON file.
    raw = {
        key: source[key]
        for key in (
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
        )
        if key in source
    }
    return {
        "source_id": str(identity),
        "number_process": number,
        "degree": degree,
        "filing": filing.date(),
        "class_code": class_code,
        "class_name": str(process_class.get("nome") or "")[:255],
        "org_code": org_code,
        "org_name": str(org.get("nome") or "")[:255],
        "municipality_code": (
            positive_code(org["codigoMunicipioIBGE"]) if org.get("codigoMunicipioIBGE") else None
        ),
        "subjects": subjects,
        "movements": movements,
        "raw": raw,
        "payload_hash": digest(raw),
        "source_updated_at": timestamp(source.get("dataHoraUltimaAtualizacao")),
        "source_timestamp": timestamp(source.get("@timestamp")),
    }
