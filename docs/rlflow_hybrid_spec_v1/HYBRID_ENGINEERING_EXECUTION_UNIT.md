# Checkpoint 57 — finite original-cap engineering execution unit

Status: final validation passed, evidence archived, ready to commit. Necessary
old regression `7016` ended `e6dd4a`/exit 0. Checkpoint 56 is committed as
`9e01e09`. This is a trusted SDK, not an HTTP route or a new scheduler.

## Delivered behavior and acceptance boundary

`EngineeringExecutionUnit(runtime, original_lease, original_output_service)`
binds one already registered engineering lease, strongly retained by its actual
Runtime. `run(original_token, idempotency_key=..., expected_state_version=...)`
performs the existing fixed readonly worker, sealed result collection, original
STOP/reap/Source and input FD closure, actual Pool FREE, original guarded core
single-inode write, actual candidate readback and 21-case readonly AST disposition.
It returns `MACHINE_ACCEPTED_PENDING_REVIEW`, never Goal completion or independent
Reviewer approval. There is no model, GPU, arbitrary command, new worker protocol,
authority renewal, copied capability, or production migration.

The first explicit CAS is checked inside the actual HANDOFF writer. Its exact
client body is bound by the original HANDOFF idempotency hash. A stale/invalid
preacceptance cannot poison the unit; any retained valid HANDOFF attempt, including
an unknown COMMIT result, permanently binds the body. Changing it is a conflict.
Each lease can have only one unit. Old human HTTP control and units exclude each
other in both constructor directions. Direct Runtime/core entries cannot bypass
the unit operation or cancellation gates.

`cancel()` latches before waiting on original Pool/Store locks. Final spawn,
G-release, candidate pwrite and new machine-disposition COMMIT gates observe it.
An already entered physical effect is not undone; STOP and original entered-write
readback may continue without authorizing new execution or machine acceptance.
Cancellation is permanent. Cleanup is limited to this original lease; unknown PID
does not mint terminal/FREE or refund its reserved exposure. This does not claim
atomic interruption of a syscall after its final effect-entry boundary.
Pure PID/live/original Runtime+Unit+lease registry checks precede the latch;
complete procfs identity verification follows it. Concurrent cleanup returns
each call's local complete/error result, not a shared diagnostic flag.

Unknown startup closes only individually identity-verified original parent FDs,
keeps Source UNKNOWN and retains exposure. Strict Source shutdown still rejects
it. Explicit original-owner safety shutdown can retire a physically closed parent
owner only for no returned Popen/no producer identity/all original FDs closed;
partial close or an actual Popen object with unverified identity retains the
original owner. Neither path generates terminal/FREE or refund. Unit cleanup
never invokes global owner shutdown or closes another lease's resources.

`resume()` never calls Start/run, sends G or writes the candidate again. It uses
only retained original result/material capabilities and actual persisted facts.
An entered complete write can reconcile and finish original readonly acceptance;
partial/no-after output remains UNKNOWN. Missing retained raw result, pre-write
interruption or unknown startup returns conservative UNKNOWN, not a new handoff.
Cold attachment, replacement construction and fork cannot reconstruct permission.

## Required verification

- One actual SDK call, writer-wait stale CAS with zero spawn, then valid body;
  one pwrite, real process reap/full Source FD closure/Pool FREE, 21-case
  machine pending-review result and immutable audit/snapshot/recovery.
- Real concurrent cancellation while the original writer owns Pool: after Popen
  before G, opened original RW FD before pwrite, and before machine COMMIT.
  Verify zero corresponding effect, actual FD closure and no new acceptance.
- Original HANDOFF/Popen/G/write/acceptance lost outcomes: same-body resume
  never repeats Popen/G/pwrite; unknown PID retains one occupied slot.
- HTTP mutual binding, original/copied capability, actual fork and prestart STOP.
- Independent incremental review and necessary Runtime/control/core regressions;
  do not rerun unchanged completed UI/review/Checkpoint 56 evidence.

## Remaining gaps

Only the already approved fixed add-patch profile is executable. A machine
disposition is not independent Reviewer/condition coverage, generic Engineer,
Codex native dispatch, arbitrary process-tree STOP, strict OS resource isolation,
trusted invoice usage, new-install/migration or 24h/8h long-running acceptance.
The original M0–M5 Goal and these gaps remain active; no new external authority
has been inferred. There is currently no new user-decision blocker.

## Final evidence

Raw logs are retained under `audit/hybrid-v1/checkpoint-57-*.log`.
First two smoke attempts ended in test-fixture failures: incoherent injected
metadata triggered the pre-existing Controller integrity guard, then frozen UTC
violated the pre-existing strictly later machine-disposition timestamp. Actual
competing durable noop event and explicit synthetic clock microsecond step fixed
these fixtures; no production validator was weakened.

New module r3: 10 passed/1 failed/2 teardown errors in 205.12s. The failed FREE
expectation after lost HANDOFF was incorrect under the original no-PID lineage
contract; unknown Popen teardown exposed early parent-FD cleanup denial. Fixes
retain UNKNOWN/occupied=1, never fabricate a terminal. Independent incremental
review also found and closed shared cleanup-result race and latch-before-IO.
Targeted r4: 3 passed in 38.23s (lost HANDOFF plus actual concurrent UNKNOWN
cleanup; actual unknown Popen; cancel before held identity IO/last G).
Source r5: 2 passed in 5.91s (partial close/safety retry/other-source preservation;
actual Popen object with missing identity cannot retire until its own finite
watchdog exits). Independent review found no remaining confirmed MUST; it did
not execute tests and is not product independent Reviewer acceptance.

Necessary regression freezes 287 inputs, SHA256
`1273a5d854cb11c6dd35b6d7e16cd544a8f6d8fcbb200e588e550d9cc7fd8a5e`.
Runtime/control/Source modules and representative original core application,
last-write guards, entered-write readback and machine acceptance are included.
No schemas, UI or historical fact bytes changed, so unchanged completed UI and
the previous 2214-test full-regression evidence are not rerun or relabelled fresh.
Necessary regression: 78 passed, 2 warnings in 630.35s. All 287 frozen inputs
match during and after execution; compilation/dependency/diff checks pass.
Final evidence: `evidence/checkpoint-57-final-tests.txt`,
`checkpoint-57-final-inputs.sha256`, `checkpoint-57-log-sha256.txt`.
New cases use actual composite r3 plus affected r4/r5 evidence, not a falsely
claimed fresh all-new-module rerun. No live tests remain. Commit follows these
checks; the original Goal remains active.

## SDK use

```python
from rlflow.hybrid_engineering_execution_unit import EngineeringExecutionUnit
from rlflow.hybrid_candidate_output_service import CandidateOutputService

# Requires existing approved fixed engineering WorkingPlan, original registered
# lease and token in this exact live Runtime. None can be recreated from JSON.
unit = EngineeringExecutionUnit(runtime, lease, CandidateOutputService(runtime))
receipt = unit.run(token, idempotency_key="repair_once",
                   expected_state_version=runtime.store.version())
# unit.cancel() latches immediately; unit.resume() never starts/releases/writes.
```
