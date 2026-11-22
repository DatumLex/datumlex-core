"""Versioned SGT civil-liability hierarchy, with source codes preserved."""

import json
from pathlib import Path

CATALOG = json.loads(Path(__file__).with_name("tpu_civil_liability.json").read_text(encoding="utf-8"))
ROOT = 10431
SUBJECTS = {item["code"]: item for item in CATALOG["subjects"]}


def branch_codes(code):
    codes = {code}
    for item in CATALOG["subjects"]:
        if item["parent"] in codes:
            codes.add(item["code"])
    return codes


def primary_subject(codes):
    def depth(code):
        return sum(code in branch_codes(parent) for parent in SUBJECTS)

    return min(codes, key=lambda code: (-depth(code), code))
