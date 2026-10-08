# Source-bound persistent preparation (checkpoint34)

This internal component prepares non-executing material. It does not complete
T11, authorize a worker, reserve budget, grant a writer/controller lease, or
prove model account access. `start()` still rejects unconditionally. No new
HTTP, Dashboard, CLI dispatch or automatic reconciliation path is enabled.

## Transaction boundary

Protected startup fixes an actual `Store`, immutable `Registry`,
`SnapshotBuilder`, `CodexExecAdapter`, project, data mode and Store epoch.
Request JSON contains only a bounded request identity, Goal reference, role
and context; it cannot select source paths, resource limits or an owner.

1. Resolve the current contract and human approval using their complete indexed
   original event proofs in one actual read transaction.
2. Outside the business writer, copy the explicit finite source manifest and
   build a provisional native bundle. Verify the copied bytes/inventory and the
   original adapter-issued bundle. Engineer write directories must fit the
   contract's relative write scope and not intersect protected paths.
3. Under the Store writer and `BEGIN IMMEDIATE`, require the bound actual service
   and its active guard, compare actual issued material bytes, reload current
   sources, enforce global CAS, epoch, Registry and consent lifetime, then append
   the immutable intent containing the original expected seal.
4. Only after that intent commits, publish the original provisional bundle.
5. Verify material again outside the writer. Reload and revalidate sources in
   the completion transaction, verify the original intent event proof, preserve
   its exact original context, and append a single immutable result.

The expected seal includes the original manifest and file hashes, exact lengths
and directory identities. The packet and result-schema canonical bytes must
match their hashes/lengths; the profile must match the original approval witness.
Snapshot descriptor validation shares the builder's IO-free finite manifest
validation, including depth, names, directory count and ancestor collisions.

`PREPARED` describes known material and source verification at preparation time;
it is not an atomic filesystem freeze or later execution permission. All release
gates remain `UNVERIFIED`. No arbitrary in-process Python sandbox is claimed.

## Historical facts, retries and crash windows

Two optional private collections, `hybrid_preparation_intents` and
`hybrid_preparation_results`, are excluded from legacy hot views. They use the
existing single-writer append-only events and projection transaction, not a
second database/controller.

The same request key returns the original intent/result without copying,
re-probing, publishing or generating a new result. A changed request with that
key is rejected. Expiry, revocation or a later contract does not turn historical
facts into current authority; historical reads validate original point proofs
and original Registry bindings without requiring today's head or disk.

An intent with no result stays pending on ordinary retry. Explicit point-key
`reconcile()` currently records an immutable `UNKNOWN` result with no material or
source grant. It never scans directories, adopts a disk manifest, rebuilds,
calls a model, or changes `UNKNOWN` into `PREPARED`. This conservative first slice
does **not** implement restart adoption from the original core-committed seal.
Published foreign/unknown material is preserved after failures. Orphan retention
and bounded storage reclamation are still required before full runtime release.

## Read and recovery closure

Live writer and historical point reads share a 64MiB raw/expanded/node envelope
per actual transaction, including repeated blob aliases. SQL caps raw values
before JSON allocation. The budget allows literal marker-looking JSON's encoded
expansion without interpreting it as caller authority. Per-record decoded cap
remains 4MiB; packet canonical cap remains 256KiB. Default single preparation
event proof also has a 64MiB envelope. These are finite read bounds, not a disk
quota or kernel IO timeout.

Audit, manual snapshots, recovery and optional periodic snapshots validate Goal
proofs, then Authority proofs, then Preparation proofs. Preparation callbacks
require an exact format2 envelope, one original object, legal empty collection
markers, no delete/extra mutation, original producer/type/hash/version and exact
referenced facts. Rehashed snapshots cannot replace original events.

Periodic maintenance retains its existing conservative default 32MiB total
budget and safely defers oversized material; the pathological legal literal
encoding capacity test explicitly uses 64MiB and a finite 30-second deadline.
Historical point validation is not an independent whole-event-chain audit.

Preparation replay additionally uses a shared 64MiB blob-decoding budget per
event. Transition validation and actual state application reuse that decoded
payload, so marker-looking literal values are not decoded again by the legacy
path. This is not a claim that all legacy SQL/event/snapshot JSON pre-reading is
bounded by a single audit-wide memory envelope. A malformed self-reference test
is rejected by content SHA mismatch; it does not demonstrate traversal of a
cryptographically valid content-addressed cycle. A hash-correct deep DAG tests
sanitized recursion failure.

## Validation status

Checkpoint34 has completed independent slice review and central regression.
Root's nine-module regression r5 reached terminal exit0: 366 passed, one existing
Starlette warning, 75.86 seconds, including actual legal large-literal material
through persistence, audit, manual/periodic snapshot, recover and retry. The
prior r3 had one fixture failure: raw budget rejection occurred
before the intended repeated-alias expanded-budget path; its failing log is
retained and the fixture now requires the first blob parse before expansion
rejection (r4: 363 passed, 61.46 seconds). No execution acceptance is claimed.
The independent original session 81090
completed those same nine modules once (366 passed, 76.31 seconds, unchanged
source/test/schema hashes), but that evidence predates the preparation replay
decoding fix. The new service-only regression reached actual terminal exit0:
root session74480, 43 passed/31.78 seconds; independent session73704,
43 passed/31.94 seconds, 15 source/test/schema hashes unchanged. Independent
final review reports no remaining MUST_FIX in this preparation slice. Root's
central full original session71114 reached actual terminal exit0: 1197 passed,
32 existing external/H1 skips, one existing Starlette warning, 350.10 seconds.
All 15 frozen source/test/schema hashes remained unchanged. Compileall, pip check
and diff checks passed. Full evidence and preserved earlier failures are recorded
in `evidence/checkpoint-34-final-tests.txt`. A 600-level deep-DAG fixture
initially reached the later record-shape rejection rather than the intended
recursion path (r6: 370 passed, one fixture failure); the fixture now uses 1200
levels without changing or weakening the product checks.

No checkpoint32 browser/UI result or earlier performance measurement is relabeled
as evidence for this change. Full M0–M5, B1, long-running validation, actual
engineering/research loops and reliable execution/recovery remain outstanding.
