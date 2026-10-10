---
name: rlflow
description: Submit an unapproved goal proposal or an explicit original finite-scope STOP suggestion to an existing rlflow Hybrid project, and read its request status or report. Use from the target project, not to approve, dispatch models, run training, or manage unrelated software.
---

Use the single `rlflow client` entry in the user's target project root. The trusted launcher must provision `RLFLOW_CONTROL_ORIGIN` and a short-lived `RLFLOW_REQUEST_TOKEN`. Read `.rlflow/project.yaml` for the registered project; never replace the trusted destination, acquire human login/CSRF credentials, or install credentials in the repository.

For a natural-language goal, draft an explicit Hybrid 1.1 Goal proposal preserving the user's scope, required conditions, evaluation data, budget and stop rules. Consult the project's established contract examples/schema; do not invent authorization, resource delegation or approval. Explain the proposed boundaries to the user. Missing constraints require clarification, not silently broader defaults.

Submit with `rlflow client submit-goal --proposal <proposal.json> --key <original-key>`. Keep the same key and exact proposal if the response is lost. Submission stores only a non-authoritative suggestion: AWAITING_HUMAN means no Core Goal has been accepted and no worker/model has started. The human operator reviews the full proposal/hash in Dashboard and explicitly forwards it through the original Core Draft service. This is not approval.

Use `rlflow client status --request <request_id>` or `rlflow client report --request <request_id>`. Report ADOPTED only when the server proves the original Core DRAFT receipt; DRAFT remains unapproved and non-executable. UNKNOWN is unresolved, not success. STALE means the frozen command was not accepted; require a fresh explicit proposal rather than auto-rebasing or changing an unknown command's key. Do not loop on unchanged failures.

For a STOP suggestion, require a trusted, explicit original finite scope JSON containing `scope_sha256` and ordered `items`, each with `project_id`, `data_mode: fixture`, `store_epoch`, `task_id`, and `stop_action`. Show every target to the user. Never infer the whole scope from the current project, fabricate a scope, or silently reinterpret a project/Goal STOP as stopping all bound projects. If this scope or the requested capability is unavailable, report the gap.

Use `rlflow client request-finite-stop --scope <scope.json> --key <original-key>` only with that exact scope. This saves a suggestion, not a STOP command or execution permission. A human operator authorized for every target must explicitly confirm and forward it in Dashboard. The original owner then performs the original finite STOP; the suggestion route needs durable inbox I/O before cancellation and does not replace the independent direct emergency STOP route. An inbox failure means forwarding is unconfirmed.

Read the same request after a lost response; do not automatically forward, change actor/key, or resume cleanup. STOPPED_AS_OF_RETURN is evidence for the listed original scopes as of the original return, not a durable aggregate, a current probe, or Goal completion. PARTIAL_OR_UNKNOWN and UNKNOWN do not prove all resources released. Only the original forwarding human may explicitly resume unknown cleanup; ordinary retry is read-only once an original result exists. A cold or closed owner cannot reconstruct physical cleanup from durable intent alone.

Pause, arbitrary process-tree STOP, and whole Goal STOP are not implemented in this client. Do not substitute legacy CLI pause/stop, human approval endpoints, shell process killing, or paid model/GPU execution. Natural-language invocation itself is not authorization.
