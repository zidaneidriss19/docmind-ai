"""Read-only checks against the packaged release endpoint."""

import argparse
import json
from urllib.error import HTTPError
from urllib.request import urlopen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    for path in ("/health", "/ready"):
        with urlopen(base + path, timeout=10) as response:
            if response.status != 200 or json.load(response) != {"status": "ok"}:
                raise SystemExit(f"{path} is not healthy.")

    with urlopen(base + "/", timeout=10) as response:
        html = response.read().decode()
        if 'id="root"' not in html or '/assets/' not in html:
            raise SystemExit("Production frontend assets were not served.")
        if "frame-ancestors 'none'" not in response.headers.get("Content-Security-Policy", ""):
            raise SystemExit("Frontend frame policy is missing.")

    for path, expected in (("/api/v1/users/me", 401), ("/openapi.json", 404)):
        try:
            with urlopen(base + path, timeout=10) as response:
                status = response.status
        except HTTPError as exc:
            status = exc.code
        if status != expected:
            raise SystemExit(f"{path} returned {status}, expected {expected}.")
    print("Production gateway, compiled frontend, API, database and private routes passed.")


if __name__ == "__main__":
    main()
