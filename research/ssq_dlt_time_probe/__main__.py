"""Run one offline synthetic verification; performs no GET or POST."""
import argparse
import json
from pathlib import Path

from .verifier import Inputs, verify_offline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--openssl", required=True, type=Path)
    args = parser.parse_args()
    source = args.input_dir
    receipt = verify_offline(Inputs(source / "payload.txt", source / "request.tsq", source / "response.tsr",
                                     source / "cacert.pem", source / "tsa.crt"), args.output, args.openssl)
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt["technical_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
