"""Trusted role definitions. Native subagent discovery is deliberately not used."""
import hashlib
from pathlib import Path
import tomllib
from .contracts import ROLES
from .store import Conflict

ROOT = Path(__file__).resolve().parents[1]


def load_role(role, root=None):
    root = Path(root or ROOT)
    if role not in ROLES:
        raise Conflict('unknown role')
    path = root / 'roles' / (role + '.toml')
    if path.is_symlink():
        raise Conflict('role definition must not be a symlink')
    raw = path.read_bytes()
    try:
        config = tomllib.loads(raw.decode())
    except (ValueError, UnicodeError) as exc:
        raise Conflict('invalid role TOML') from exc
    keys = {'name', 'description', 'schema', 'candidate_access', 'scratch_access', 'tools', 'developer_instructions'}
    if set(config) != keys or config['name'] != role:
        raise Conflict('role keys invalid; model and effort belong to dispatch policy')
    if (config['candidate_access'] != ('write' if role == 'Engineer' else 'read')
            or config['scratch_access'] != 'write' or config['tools'] != ['cpu_exec']
            or config['schema'] != role + 'Result.json'):
        raise Conflict('role authority differs from enforced CPU boundary')
    if any(not isinstance(config[k], str) or not config[k].strip()
           for k in ('description', 'developer_instructions')):
        raise Conflict('role instructions must be nonempty')
    return {**config, 'sha256': hashlib.sha256(raw).hexdigest()}
