#!/usr/bin/env python3
"""
Vendor-side license creation tool (not distributed to clients).

Usage:
    python tools/create_license.py --private-key private.pem --out license.json --fingerprint <FP> --type trial --start 2026-06-24 --end 2026-07-08
    python tools/create_license.py --private-key private.pem --out license.json --fingerprint <FP> --type full

This script signs the license JSON using RSA private key and outputs a
license.json containing the signature (base64) and fields.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Dict, Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


def _canonical_license_bytes(doc: Dict[str, Any]) -> bytes:
    filtered = {k: v for k, v in doc.items() if k != 'signature'}
    return json.dumps(filtered, separators=(',', ':'), sort_keys=True).encode('utf-8')


def load_private_key(path: Path) -> RSAPrivateKey:
    data = path.read_bytes()
    return serialization.load_pem_private_key(data, password=None)


def sign_license(priv: RSAPrivateKey, doc: Dict[str, Any]) -> str:
    data = _canonical_license_bytes(doc)
    sig = priv.sign(data, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode('ascii')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--private-key', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--fingerprint', required=True)
    p.add_argument('--type', choices=['trial', 'full'], required=True)
    p.add_argument('--start')
    p.add_argument('--end')
    args = p.parse_args()

    doc: Dict[str, Any] = {
        'fingerprint': args.fingerprint,
        'license_type': args.type,
    }
    if args.type == 'trial':
        if not args.start or not args.end:
            raise SystemExit('Trial requires --start and --end')
        doc['start_date'] = args.start
        doc['end_date'] = args.end

    priv = load_private_key(Path(args.private_key))
    sig = sign_license(priv, doc)
    doc['signature'] = sig

    Path(args.out).write_text(json.dumps(doc, indent=2), encoding='utf-8')
    print(f'Wrote {args.out}')


if __name__ == '__main__':
    main()
