"""Bounded, project-scoped dashboard authentication; never execution authority.

Credentials are provisioned by the trusted local operator, not by HTTP routes.
Session and bearer secrets are only kept as hashes and are never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from dataclasses import dataclass

ROLES = frozenset({"viewer", "operator", "approver"})
MAX_TTL = 900


@dataclass(frozen=True)
class Principal:
    id: str
    kind: str
    roles: frozenset[str]
    projects: frozenset[str]

    def __post_init__(self):
        object.__setattr__(self, "roles", frozenset(self.roles))
        object.__setattr__(self, "projects", frozenset(self.projects))
        if not isinstance(self.id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", self.id) is None or self.kind not in {"human", "agent"}:
            raise ValueError("invalid principal")
        if not self.roles or not self.roles <= ROLES or not self.projects:
            raise ValueError("invalid scope")
        if len(self.projects) > 128 or any(not isinstance(p, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", p) is None for p in self.projects):
            raise ValueError("invalid project scope")
        if self.kind == "agent" and "approver" in self.roles:
            raise ValueError("agents cannot receive human approval authority")

    def allows(self, project: str, role="viewer"):
        # Role inheritance applies only to observation, never operator/approver.
        return project in self.projects and (role == "viewer" or role in self.roles)


@dataclass(frozen=True)
class Credential:
    principal: Principal
    salt: str
    digest: str

    def __post_init__(self):
        if self.principal.kind != "human" or re.fullmatch(r"[0-9a-f]{32}", self.salt) is None or re.fullmatch(r"[0-9a-f]{64}", self.digest) is None:
            raise ValueError("invalid human credential")

    @classmethod
    def create(cls, principal, passphrase):
        if principal.kind != "human" or not isinstance(passphrase, str) or not 20 <= len(passphrase) <= 1024:
            raise ValueError("human login requires a passphrase of 20–1024 characters")
        salt = secrets.token_hex(16)
        return cls(principal, salt, cls.derive(passphrase, salt))

    @staticmethod
    def derive(passphrase, salt):
        return hashlib.pbkdf2_hmac("sha256", passphrase.encode(), bytes.fromhex(salt), 210_000).hex()


@dataclass(frozen=True)
class Access:
    principal: Principal
    expires_at: float
    csrf: str | None
    method: str


class AuthStore:
    """In-memory, revocable credentials. Restart signs everyone out safely."""

    def __init__(self, credentials=(), *, ttl=MAX_TTL, max_sessions=128, clock=time.monotonic):
        if not 1 <= ttl <= MAX_TTL or not 1 <= max_sessions <= 128:
            raise ValueError("invalid authentication bounds")
        credentials = tuple(credentials)
        self.credentials = {c.principal.id: c for c in credentials}
        if len(self.credentials) > 128 or len(self.credentials) != len(credentials):
            raise ValueError("too many principals")
        self.ttl, self.max_sessions, self.clock = ttl, max_sessions, clock
        self._sessions = {}
        self._lock = threading.Lock()
        # Rate-limit globally, not by untrusted forwarded addresses or user ID.
        self._login_times = []
        self._dummy_salt = secrets.token_hex(16)

    @staticmethod
    def _key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def _expire(self):
        now = self.clock()
        for key in tuple(self._sessions):
            if self._sessions[key].expires_at <= now:
                del self._sessions[key]

    def login(self, principal_id, passphrase):
        if not isinstance(principal_id, str) or not isinstance(passphrase, str) or len(principal_id) > 160 or len(passphrase) > 1024:
            return None
        with self._lock:
            now = self.clock()
            self._login_times = [t for t in self._login_times if now - t < 60]
            if len(self._login_times) >= 10:
                return None
            self._login_times.append(now)
            credential = self.credentials.get(principal_id)
            try:
                supplied = Credential.derive(passphrase, credential.salt if credential else self._dummy_salt)
            except UnicodeError:
                return None
            expected = credential.digest if credential else "0" * 64
            if not hmac.compare_digest(supplied, expected) or credential is None:
                return None
            return self._issue(credential.principal, "session", secrets.token_urlsafe(32), self.ttl)

    def _issue(self, principal, method, csrf, ttl):
        self._expire()
        if len(self._sessions) >= self.max_sessions:
            return None
        token = secrets.token_urlsafe(32)
        self._sessions[self._key(token)] = Access(principal, self.clock() + ttl, csrf, method)
        return token, self._sessions[self._key(token)]

    def issue_bearer(self, principal, *, ttl=300):
        """Trusted local integration API, deliberately NOT an HTTP endpoint.

        M1 bearer integrations are observation-only, even for human principals.
        """
        if principal.roles != frozenset({"viewer"}) or not 1 <= ttl <= min(self.ttl, 300):
            raise ValueError("bearer scope must be short-lived and read-only")
        with self._lock:
            return self._issue(principal, "bearer", None, ttl)

    def resolve(self, token, method):
        if not isinstance(token, str) or not 20 <= len(token) <= 128:
            return None
        with self._lock:
            self._expire()
            access = self._sessions.get(self._key(token))
            return access if access and access.method == method else None

    def revoke(self, token):
        with self._lock:
            self._sessions.pop(self._key(token), None)
