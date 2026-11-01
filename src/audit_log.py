"""Append-only, hash-chained episode log (REQ-DAT-001).

Each record stores the hash of the previous record, so any edit or deletion
breaks the chain and is detected by verify().
"""
import hashlib
import json
import os
from datetime import datetime, timezone

GENESIS_HASH = "0" * 64


def _digest(prev_hash, body):
    canon = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + canon).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.prev = GENESIS_HASH
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        self.prev = json.loads(line)["hash"]

    def append(self, body):
        body = dict(body, ts=datetime.now(timezone.utc).isoformat())
        h = _digest(self.prev, body)
        rec = {"prev_hash": self.prev, "hash": h, "body": body}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.prev = h
        return rec


def verify(path):
    """Return (ok, index_of_first_bad_record_or_None)."""
    prev = GENESIS_HASH
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(l for l in f if l.strip()):
            rec = json.loads(line)
            if rec["prev_hash"] != prev or _digest(prev, rec["body"]) != rec["hash"]:
                return False, i
            prev = rec["hash"]
    return True, None
