"""Local acceptance evidence binds the exact executable control-plane sources."""
from pathlib import Path
import hashlib
import json
from .store import sha, Conflict


def code_identity():
    root = Path(__file__).resolve().parents[1]
    from .releases import files as release_files
    files = {name: hashlib.sha256(p.read_bytes()).hexdigest() for name, p in release_files(root).items()}
    return sha(files)


def require_tests(root):
    path = Path(root) / "runtime/self-test.json"
    result = json.loads(path.read_text())
    if result.get("exit_code") != 0 or result.get("code_identity") != code_identity():
        raise Conflict("self-test evidence missing/stale/failed; run ./rlflow self-test")
    return result
