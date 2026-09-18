"""Read-only system smoke against an already running local backend."""

import json
from urllib.error import HTTPError
from urllib.request import urlopen

BASE = "http://127.0.0.1:8000"


def get(path):
    with urlopen(BASE + path, timeout=10) as response:
        assert response.status == 200
        return json.load(response)


def main():
    assert get("/api/health/")["status"] == "ok"
    result = get("/api/statistics/")
    count = result["metrics"]["process_records"]
    assert sum(item["count"] for item in get("/api/instances/")["series"]) == count
    assert get("/api/processes/?page_size=1")["count"] == count
    distribution = get("/api/distribution/")
    assert distribution["denominator"] == result["metrics"]["binary_denominator"]
    assert sum(row["count"] for row in distribution["series"]) == distribution["denominator"]
    assert get("/api/statistics/?outcome=granted")["metrics"] == result["metrics"]
    try:
        get("/api/statistics/?court=TJSP")
    except HTTPError as error:
        assert error.code == 400
    else:
        raise AssertionError("Invalid court was accepted")
    print(json.dumps({"result": "passed", "loaded_process_records": count, "metrics": result["metrics"]}))


if __name__ == "__main__":
    main()
