# Checkpoint 58 — one-call original CPU experiment

Status: final validation passed, evidence archived, ready to commit. Checkpoint
57 is committed as `96a98e4`. Actual new positive smoke
passed: session `40234`, terminal `1c39e5`, exit 0, one case in 25.98s. Boundary
r2 (`58063`/`0cba12`) ended with 11 passed/2 test-injector failures/1 deselected
in 203.44s. Both failed on non-CPU event `None` stage string concatenation,
before target rollback; restrict injection to actual CPU appraisal events,
not weaken guards. Only two failed cases and three new necessary boundary cases
rerun in r3 (`84671`/`8c5089`), exit 0: 5 passed in 97.56s. This is composite
17-case new-profile evidence, not a falsely claimed fresh all-module rerun.

Necessary regression (`78623`/`3004d9`) ended exit0: 27 passed in438.20s,
shared original engineering unit,
original CPU trial/appraisal/cold decision modules. 290 inputs frozen SHA256
`519ecd240f6a8fb1c5cd03d8591dc2ea8efb6be8915bd635a6948c3b2a0ca247`.
Source/test/schema inputs stayed unchanged until actual termination. Independent
incremental High review found no confirmed MUST on the new code; it did not run
tests or write. All290 frozen inputs match during/after run; compilation, dependency
and diff checks pass. Final evidence is `evidence/checkpoint-58-final-tests.txt`,
`checkpoint-58-final-inputs.sha256`, `checkpoint-58-log-sha256.txt`. No live tests
remain; checkpoint commit follows these checks and full Goal remains active.

## Actual delivery and acceptance

`CpuTrialExecutionUnit(runtime, original_lease, original_assessment_service)`
requires the already approved fixed CPU PI grant and registered original lease.
One `run(original_token, idempotency_key=..., expected_state_version=...)` does
original HANDOFF/CAS, actual fixed CPU program and sealed 384-coordinate source,
original result collection, STOP/reap/all original FDs closed/Pool FREE, original
current-contract appraisal and independent arithmetic raw machine disposition.
Output is `EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW` and next action requests
independent review. No Goal completion, condition coverage, independent Reviewer,
model, GPU, arbitrary command, candidate file write or production migration.

The shared private finite operation preserves Checkpoint 57's original object
identity, first HANDOFF writer CAS, immutable body hash, cancellation before
blocking identity IO/locks, last spawn/G fence and per-call local cleanup result.
Runtime has one canonical `_execution_units` registry; old `_engineering_units`
is the same dict, not a competing registry. Engineering-specific RO/RW cleanup
remains in its engineering override; CPU has no candidate write descriptor.
Old human HTTP control and both units exclude each other; no HTTP was added.

Cancellation also reaches the actual last new appraisal/decision COMMIT gate
after original Controller and consent checks. Direct service/collector calls
cannot bypass the original active unit. Cleanup closes only this lease's actual
source and never another task or a global owner. Unknown HANDOFF/Popen keeps
UNKNOWN and occupied exposure, never a fabricated terminal/FREE/refund.

`resume()` cannot Start/run/send G/recollect/candidate-write. It requires the
retained original raw result and actual STOP/FREE. Readonly evaluation can finish
only under the existing strict current Controller/Goal/Registry constraints;
there is no automatic renewal. Phase requests and full original canonical fact
attempts are retained at the real held writer before uncertain COMMIT. Known
pre-write stale rejection does not poison a phase; uncertain attempts retry the
exact original fact, not resampled UTC/monotonic data. Existing exact duplicates
are history only and do not reactivate authority. Missing raw stays UNKNOWN;
expired or changed current authority rejects new appraisal/decision.

The `evidence_activation` in a stored fact is its recorded AS-OF designation.
Cached/duplicate unit output is not a new current permission check. Use the
existing bounded cold appraisal reader for current-versus-historical activation;
it remains read-only after original Runtime shutdown. The SDK is trusted-core
only; no JSON/cold/fork can reconstruct an executable lease/unit.

## Verification required

- Actual one call: exact 384 samples/source SHA, independent recurrence and
  counts `[96,101,104]`, actual process exit/reap/FD closure/FREE, one experiment
  consumption, duplicate/resume no repeat, audit/snapshot/recovery.
- Actual writer-wait initial CAS stale gives zero Popen and can accept a valid
  later body; no changing an accepted original body or mixed profile/service.
- Last G, appraisal COMMIT and decision COMMIT cancellation: corresponding
  effect/fact absent, real cleanup, no candidate pwrite and no new machine fact.
- Original collect/STOP/appraisal/decision lost results and pre-COMMIT rollback
  resume without a second Popen/G/experiment charge or timestamp rebasing.
- Post-STOP TTL and actual Controller revision refuse new activation; exact
  existing old receipts remain historical. Copied lease, fork and HTTP binding
  reject; preserve unchanged original engineering shared-lifecycle acceptance.

## Remaining gaps

Only the existing `FIXED_CPU_PI_TRIAL_V1` experiment is executable. Compatible
CPU enforcement and original kernel-reported measurement are explicitly partial,
not strict OS/whole-tree/invoice enforcement. Generic/native Engineer, scientific
independent Reviewer, global conditions, whole Goal, fresh-install/migration and
24h fixture/8h UI acceptance remain open. No new user decision is currently
required; original model/GPU/production authority boundaries remain unchanged.

## SDK use

```python
from rlflow.hybrid_cpu_execution_unit import CpuTrialExecutionUnit
from rlflow.hybrid_cpu_assessment_service import CpuAssessmentService

# Original approved fixed CPU grant, registered lease/token and this exact live
# Runtime are required; none is reconstructed from historical JSON or cold Store.
unit = CpuTrialExecutionUnit(runtime, lease, CpuAssessmentService(runtime))
receipt = unit.run(token, idempotency_key="experiment_once",
                   expected_state_version=runtime.store.version())
# unit.cancel() latches first; unit.resume() never restarts the physical trial.
```
