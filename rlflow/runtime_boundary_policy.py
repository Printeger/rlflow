"""Mandatory installation policy, included in the verified control release.

UNBOUND is an explicit legacy installation, never inferred from a missing file.
A guarded installation must generate a BOUND descriptor in its own new release;
HTTP, worker requests and environment variables cannot select this policy.
This source checkout does not migrate any existing installation.
"""

DESCRIPTOR = {'version': 1, 'mode': 'LEGACY_UNBOUND'}
