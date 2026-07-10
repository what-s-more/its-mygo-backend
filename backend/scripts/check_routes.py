from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


REQUIRED_PATHS = [
    "/api/v1/home/banners",
    "/api/v1/admin/home-banners",
    "/api/v1/products",
]


def read_live_paths(base_url: str) -> set[str]:
    url = base_url.rstrip("/") + "/openapi.json"
    with urllib.request.urlopen(url, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return set(payload.get("paths", {}).keys())


def read_local_paths() -> set[str]:
    from main import app

    return set(app.openapi().get("paths", {}).keys())


def report(name: str, paths: set[str]) -> bool:
    print(f"\n{name}")
    ok = True
    for path in REQUIRED_PATHS:
        exists = path in paths
        ok = ok and exists
        print(f"  {'OK ' if exists else 'MISS'} {path}")
    return ok


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    local_ok = report("local code", read_local_paths())
    try:
        live_ok = report(f"live server {base_url}", read_live_paths(base_url))
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"\nlive server {base_url}\n  ERROR {exc}")
        return 2
    if local_ok and not live_ok:
        print("\nLive server is not running the current code. Stop old uvicorn/python processes and restart backend.")
    return 0 if local_ok and live_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
