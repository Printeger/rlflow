# Reliability update

Synced from the accepted local reliability candidate on 2026-09-16. Includes
object projections, explicit export/snapshot/audit, source input manifests,
generation-bound startup recovery, usage observations, resource admission,
integration/recovery reserves and controller risk routing.

Standalone workspace and STOP paths remain under ~/.local/share/rlflow-standalone.
The project runner remains unconfigured; no project history, approvals, budgets
or credentials are imported. Real quota exhaustion tests were cancelled by the
user and remain unverified. Strict tasks still require verified hard limits.

Token costs are estimates, not invoices. Missing usage remains unknown.
Legacy package semantics are preserved. Keep the SQLite ledger including blobs
when migrating; old control binaries cannot read format-2 events. Never restore
an older database to undo usage. Run storage-audit before resuming after recovery.

Tests distinguish the generic core from excluded external H1/project adapters.
External adapter skips are not positive acceptance results. A local recovery test
waits up to five seconds for the identity-bound result artifact, retaining its
no-duplicate-start and missing-exit-evidence assertions.
