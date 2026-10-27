"""Vendor tool: turn a customer's request code into a signed license key.

Not shipped. It reads the private key from the vendor folder (`TIQR_VENDOR_DIR`, default
`~/.tiqr-vendor`: `license-private.pem`, `license-public.pem`) and keeps `issued.json` there as
the issuance history. The history is also the trial registry: lose it and every machine is
eligible for a new trial. It holds customer names and working keys, so back it up, restrict it,
and keep it out of git.

    issue_license.py --request CODE --type trial
    issue_license.py --request CODE --licensedTo "Company" --days 365
"""

import argparse
import base64
import json
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from tiqr.core.license import PRODUCT_ID, PUBLIC_KEY, TRIAL_DAYS, RequestCode, parse_request_code

VENDOR_DIR = Path(os.environ.get("TIQR_VENDOR_DIR", "~/.tiqr-vendor")).expanduser()


def sign_license(payload: dict[str, Any], private_key_pem: bytes) -> str:
    """`base64(payload bytes).base64(signature)`; the signature covers the raw bytes."""
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError("The private key must be RSA")
    raw = json.dumps(payload).encode()
    signature = key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
    return f"{base64.b64encode(raw).decode()}.{base64.b64encode(signature).decode()}"


def build_payload(
    request: RequestCode, *, kind: str, licensed_to: str | None, days: int | None, now: datetime
) -> dict[str, Any]:
    if kind == "trial":
        # Forced: a trial is always 30 days, whatever is passed.
        licensed_to, days = licensed_to or request.contact or "Trial", TRIAL_DAYS
    elif not licensed_to or days is None:
        raise ValueError("--licensedTo and --days are required for paid licenses")
    elif days < 0:
        raise ValueError("--days cannot be negative")
    return {
        "product": PRODUCT_ID,
        "type": kind,
        "licensedTo": licensed_to,
        "issuedAt": now.isoformat(),
        "expiresAt": (now + timedelta(days=days)).isoformat(),
        "machineId": request.machine_id,
        "requestId": request.request_id,
    }


def _read_history(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text()) if path.exists() else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--request", required=True, help="the customer's request code")
    parser.add_argument("--type", choices=("trial", "standard"), default="standard")
    parser.add_argument("--licensedTo", dest="licensed_to")
    parser.add_argument("--days", type=int)
    parser.add_argument("--note")
    args = parser.parse_args(argv)

    private = VENDOR_DIR / "license-private.pem"
    public = VENDOR_DIR / "license-public.pem"
    if not private.exists() or not public.exists():
        parser.exit(1, f"No key pair in {VENDOR_DIR}; never generated silently\n")
    # A key signed with another pair would verify nowhere.
    if public.read_text().strip() != PUBLIC_KEY.strip():
        parser.exit(1, "The vendor public key differs from the one built into the program\n")

    # The request's type is what the customer clicked; the vendor's --type decides the license.
    request = parse_request_code(args.request)
    kind = args.type

    history_path = VENDOR_DIR / "issued.json"
    history = _read_history(history_path)
    if kind == "trial" and any(
        r["type"] == "trial" and r["machineId"] == request.machine_id and r["status"] != "revoked"
        for r in history
    ):
        parser.exit(1, "This machine has already had a trial\n")
    if (
        kind == "trial"
        and request.contact
        and any(r.get("contact") == request.contact and r["type"] == "trial" for r in history)
    ):
        sys.stderr.write(f"Warning: contact {request.contact} already had a trial elsewhere\n")

    now = datetime.now(UTC).replace(microsecond=0)
    payload = build_payload(
        request, kind=kind, licensed_to=args.licensed_to, days=args.days, now=now
    )
    key = sign_license(payload, private.read_bytes())
    previous = [
        r for r in history if r["machineId"] == request.machine_id and r["status"] == "active"
    ]
    for record in previous:
        record["status"] = "superseded"
    history.append(
        {
            "id": secrets.token_hex(8),
            "status": "active",
            "requestId": request.request_id,
            "machineId": request.machine_id,
            "contact": request.contact,
            "type": kind,
            "licensedTo": payload["licensedTo"],
            "issuedAt": payload["issuedAt"],
            "expiresAt": payload["expiresAt"],
            "supersedes": previous[-1]["id"] if previous else None,
            "note": args.note,
            "licenseKey": key,
        }
    )
    history_path.write_text(json.dumps(history, indent=2))
    history_path.chmod(0o600)
    sys.stdout.write(key + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
