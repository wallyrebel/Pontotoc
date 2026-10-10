"""Select one digest-bound request without interpolating dispatch inputs into shell."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    require_main = os.environ.get("GITHUB_REF") == "refs/heads/main"
    if not require_main:
        raise ValueError("Reviewed transport runs only from main")
    if os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch":
        inputs = event.get("inputs", {})
        request = inputs.get("request_path", "")
        if inputs.get("operation", "probe") == "probe":
            args = ["--probe"]
        else:
            if not request:
                raise ValueError("Request path required")
            args = ["--request", request]
    else:
        before = event["before"]
        if not before or set(before) == {"0"}:
            raise ValueError("Missing push base; use manual probe")
        changed = subprocess.check_output(["git", "diff", "--name-only", "--diff-filter=AM",
                                           before, event["after"], "--", "reviewed/requests/"],
                                          cwd=ROOT, text=True).splitlines()
        requests = [p for p in changed if p.endswith(".json")]
        if len(requests) > 1:
            raise ValueError("One reviewed article request per push; dispatch individually")
        args = ["--request", requests[0]] if requests else ["--probe"]
    if args == ['--request', 'reviewed/requests/pepa-slug-migration-2026-10-10.json']:
        return subprocess.call([sys.executable, str(ROOT / 'scripts/pepa_slug_migration.py')], cwd=ROOT)
    return subprocess.call([sys.executable, str(ROOT / "scripts/reviewed_publish.py"), *args], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
