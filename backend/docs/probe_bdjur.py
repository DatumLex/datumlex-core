"""Bounded, credential-free BDJur access observations for task #101.

No retry, challenge handling, source-text download, or database write is performed.
"""

import argparse
import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

URLS = [
    "https://bdjur.stj.jus.br/",
    "https://bdjur.stj.jus.br/robots.txt",
    "https://bdjur.stj.jus.br/server/api",
    "https://bdjur.stj.jus.br/entities/publication/67297921-a874-4880-b8e5-e65e235d4338",
    "https://bdjur.stj.jus.br/entities/publication/4bd0920d-0f94-4736-b099-78ddcac45022/full",
    "https://bdjur.stj.jus.br/items/9431076b-d413-4887-b648-4c346b35fda4",
]


def probe(url):
    result = {"url": url, "observed_at": datetime.now(timezone.utc).isoformat()}
    request = Request(url, headers={"User-Agent": "DatumLex-academic-feasibility/0.1"})
    try:
        with urlopen(request, timeout=20) as response:
            result.update(status=response.status, content_type=response.headers.get("Content-Type"))
    except HTTPError as error:
        result.update(status=error.code, content_type=error.headers.get("Content-Type"))
        error.close()
    except (URLError, TimeoutError, OSError) as error:
        result.update(status=None, error_type=type(error).__name__)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New output file; existing evidence is never overwritten")
    args = parser.parse_args()
    # Claim the new evidence path before issuing any network requests.
    with open(args.output, "x", encoding="utf-8") as output:
        observations = [probe(url) for url in URLS]
        report = {
            "scope": "Six public BDJur access probes; not a corpus extraction or rights approval",
            "observations": observations,
        }
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"requests": len(observations), "statuses": [row["status"] for row in observations]}))


if __name__ == "__main__":
    main()
