#!/usr/bin/env python3
"""Validate IPS example Bundles against the IPS Bundle profile in a running Matchbox.

Usage (from repo root, with `docker compose -f infra/docker-compose.yml up -d` healthy):

    python3 infra/scripts/validate_sample.py [bundle.json ...]

Defaults to the HL7 IPS IG example Bundles in backend/tests/fixtures/ips-examples/.
Prints error/warning/information counts and every error; exits 1 if any Bundle has errors.
Standard library only. Only issue metadata is printed, never resource contents.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

MATCHBOX_URL = os.environ.get("MATCHBOX_URL", "http://localhost:8080/matchboxv3/fhir").rstrip("/")
IPS_BUNDLE_PROFILE = os.environ.get(
    "IPS_BUNDLE_PROFILE", "http://hl7.org/fhir/uv/ips/StructureDefinition/Bundle-uv-ips|2.0.1"
)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "ips-examples"


def validate(path: Path) -> dict[str, object]:
    query = urllib.parse.urlencode({"profile": IPS_BUNDLE_PROFILE})
    request = urllib.request.Request(  # noqa: S310 - URL comes from trusted local config
        f"{MATCHBOX_URL}/$validate?{query}",
        data=path.read_bytes(),
        method="POST",
        headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310
            body = response.read()
    except urllib.error.HTTPError as exc:  # $validate may return 4xx with an OperationOutcome
        body = exc.read()
    result: dict[str, object] = json.loads(body)
    return result


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or sorted(DEFAULT_DIR.glob("*.json"))
    if not paths:
        print(f"No bundles found in {DEFAULT_DIR}", file=sys.stderr)
        return 2
    print(f"Matchbox: {MATCHBOX_URL}\nProfile:  {IPS_BUNDLE_PROFILE}")
    failed = False
    for path in paths:
        outcome = validate(path)
        issues = outcome.get("issue", [])
        if not isinstance(issues, list):
            print(f"{path.name}: unexpected response (no OperationOutcome)", file=sys.stderr)
            return 2
        counts = Counter(i.get("severity", "?") for i in issues)
        errors = counts["error"] + counts["fatal"]
        failed = failed or errors > 0
        print(
            f"\n{path.name}: errors={errors} warnings={counts['warning']} "
            f"information={counts['information']}"
        )
        for issue in issues:
            if issue.get("severity") in {"error", "fatal"}:
                where = ", ".join(issue.get("expression", []) or issue.get("location", []))
                text = issue.get("diagnostics") or issue.get("details", {}).get("text", "")
                print(f"  ERROR [{where}] {text}")
    print("\nRESULT:", "FAIL" if failed else "PASS (no errors)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
