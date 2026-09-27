"""Functional API tests against a running backend with seeded isolated data."""

import json
import sys
from urllib.error import HTTPError
from urllib.request import urlopen, Request

BASE = "http://127.0.0.1:8000"
PASSED = []
FAILED = []


def get(path, expected_status=200):
    try:
        with urlopen(BASE + path, timeout=10) as response:
            assert response.status == expected_status, (
                f"Expected {expected_status}, got {response.status} for {path}"
            )
            return json.load(response)
    except HTTPError as error:
        if error.code == expected_status:
            return {"status_code": error.code}
        raise


def post(path, expected_status=405):
    try:
        request = Request(BASE + path, data=b"{}", method="POST",
                         headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            raise AssertionError(f"Expected {expected_status}, got {response.status}")
    except HTTPError as error:
        assert error.code == expected_status, (
            f"Expected {expected_status}, got {error.code} for POST {path}"
        )
        return {"status_code": error.code}


def check(name, fn):
    try:
        fn()
        PASSED.append(name)
        print(f"  PASSED: {name}")
    except Exception as exc:
        FAILED.append(name)
        print(f"  FAILED: {name} — {exc}")


def main():
    print("=== DatumLex Functional API Tests ===\n")

    # --- Health ---
    check("health check returns ok", lambda:
        assert_equal(get("/api/health/")["status"], "ok", "health status"))

    # --- Successful requests ---
    result = get("/api/statistics/")
    count = result["metrics"]["process_records"]
    scope = get("/api/scope/")

    check("statistics returns valid schema", lambda: (
        assert_keys(result, ["status", "metrics", "metadata"]),
        assert_keys(result["metrics"], ["process_records", "grant_rate",
                                        "denial_rate", "binary_denominator"])
    ))

    check("scope returns available_period", lambda:
        assert_keys(scope["metadata"], ["available_period", "source"]))

    # --- Analytical consistency ---
    check("instances total matches statistics count", lambda:
        assert_equal(
            sum(item["count"] for item in get("/api/instances/")["series"]),
            count, "instances vs statistics"
        ))

    check("processes count matches statistics count", lambda:
        assert_equal(
            get("/api/processes/?page_size=1")["count"],
            count, "processes vs statistics"
        ))

    distribution = get("/api/distribution/")
    check("distribution denominator matches binary_denominator", lambda:
        assert_equal(
            distribution["denominator"],
            result["metrics"]["binary_denominator"],
            "distribution denominator"
        ))

    check("distribution series sum matches denominator", lambda:
        assert_equal(
            sum(row["count"] for row in distribution["series"]),
            distribution["denominator"],
            "distribution series sum"
        ))

    check("outcome filter does not change process volume", lambda:
        assert_equal(
            get("/api/statistics/?outcome=granted")["metrics"],
            result["metrics"], "outcome filter invariance"
        ))

    # --- Empty state ---
    check("empty period returns status empty", lambda: (
        assert_equal(
            get("/api/statistics/?start=2025-06-01&end=2025-06-01")["status"],
            "empty", "empty status"
        )
    ))

    check("empty period returns zero process_records", lambda:
        assert_equal(
            get("/api/statistics/?start=2025-06-01&end=2025-06-01")["metrics"]["process_records"],
            0, "empty process_records"
        ))

    check("empty period returns null grant_rate", lambda:
        assert_equal(
            get("/api/statistics/?start=2025-06-01&end=2025-06-01")["metrics"]["grant_rate"],
            None, "empty grant_rate"
        ))

    # --- Boundary cases ---
    available_start = scope["metadata"]["available_period"]["start"]
    available_end = scope["metadata"]["available_period"]["end"]

    check("first available day returns data", lambda:
        assert_gte(
            get(f"/api/statistics/?start={available_start}&end={available_start}")
            ["metrics"]["process_records"],
            0, "first day records"
        ))

    check("last available day returns data", lambda:
        assert_gte(
            get(f"/api/statistics/?start={available_end}&end={available_end}")
            ["metrics"]["process_records"],
            0, "last day records"
        ))

    # --- Filter by subject ---
    if scope.get("subjects"):
        subject_code = scope["subjects"][0]["code"]
        check("subject filter returns subset of total", lambda:
            assert_lte(
                get(f"/api/statistics/?subject={subject_code}")["metrics"]["process_records"],
                count, "subject filter subset"
            ))

    # --- Pagination ---
    check("pagination page_size=1 returns single result", lambda:
        assert_equal(
            len(get("/api/processes/?page_size=1")["results"]),
            1, "page_size=1 results"
        ))

    check("pagination beyond last page returns empty results", lambda:
        assert_equal(
            get("/api/processes/?page=99999&page_size=1")["results"],
            [], "beyond last page"
        ))

    check("raw_payload not exposed in processes", lambda:
        assert_not_in("raw_payload", get("/api/processes/?page_size=1")["results"][0],
                      "raw_payload exposure"))

    # --- Invalid requests → 400 ---
    invalid_cases = [
        ("invalid court returns 400", "/api/statistics/?court=TJSP"),
        ("malformed start date returns 400", "/api/statistics/?start=abc"),
        ("reversed dates return 400", "/api/statistics/?start=2025-01-01&end=2023-01-01"),
        ("out of scope date returns 400", "/api/statistics/?start=2020-01-01&end=2021-12-31"),
        ("invalid subject code returns 400", "/api/statistics/?subject=abc"),
        ("invalid outcome returns 400", "/api/statistics/?outcome=maybe"),
        ("unknown parameter returns 400", "/api/statistics/?unknown=yes"),
        ("repeated parameter returns 400", "/api/statistics/?start=2023-01-01&start=2024-01-01"),
        ("page_size over limit returns 400", "/api/processes/?page_size=101"),
    ]

    for name, path in invalid_cases:
        check(name, lambda p=path: assert_equal(
            get(p, expected_status=400)["status_code"], 400, p
        ))

    # --- Read-only (POST → 405) ---
    check("POST to statistics returns 405", lambda:
        assert_equal(post("/api/statistics/")["status_code"], 405, "POST statistics"))

    # --- Summary ---
    print(f"\n=== Results: {len(PASSED)} passed, {len(FAILED)} failed ===")
    if FAILED:
        print(f"Failed tests: {FAILED}")
        sys.exit(1)
    else:
        print(json.dumps({
            "result": "passed",
            "total": len(PASSED),
            "loaded_process_records": count,
            "available_period": scope["metadata"]["available_period"],
        }))


def assert_equal(actual, expected, label=""):
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"


def assert_keys(obj, keys):
    for key in keys:
        assert key in obj, f"Missing key: {key!r}"


def assert_gte(value, minimum, label=""):
    assert value >= minimum, f"{label}: expected >= {minimum}, got {value}"


def assert_lte(value, maximum, label=""):
    assert value <= maximum, f"{label}: expected <= {maximum}, got {value}"


def assert_not_in(key, obj, label=""):
    assert key not in obj, f"{label}: {key!r} should not be exposed"


if __name__ == "__main__":
    main()