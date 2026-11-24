"""Delivery voice allowlist; absent in internal checkouts with private test fixtures."""
import json
from pathlib import Path


def builtin_voice_allowed(voice_id, directory=None):
    policy = Path(directory or Path(__file__).parent / "voices") / "policy.json"
    if not policy.exists():
        return True
    ids = json.loads(policy.read_text(encoding="utf-8"))["builtin_voice_ids"]
    if not isinstance(ids, list) or not all(isinstance(v, str) for v in ids):
        raise ValueError("invalid delivery voice policy")
    return voice_id in ids
