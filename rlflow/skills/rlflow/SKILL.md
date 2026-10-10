---
name: rlflow
description: Submit a scoped unapproved goal proposal to an existing rlflow Hybrid project and read its request status or report. Use from the target project, not to approve, dispatch models, run training, or manage unrelated software.
---

Use the single `rlflow client` entry in the user's target project root. The trusted launcher must provision `RLFLOW_CONTROL_ORIGIN` and a short-lived `RLFLOW_REQUEST_TOKEN`. Read `.rlflow/project.yaml` for the registered project; never replace the trusted destination, acquire human login/CSRF credentials, or install credentials in the repository.

For a natural-language goal, draft an explicit Hybrid 1.1 Goal proposal preserving the user's scope, required conditions, evaluation data, budget and stop rules. Consult the project's established contract examples/schema; do not invent authorization, resource delegation or approval. Explain the proposed boundaries to the user. Missing constraints require clarification, not silently broader defaults.

Submit with `rlflow client submit-goal --proposal <proposal.json> --key <original-key>`. Keep the same key and exact proposal if the response is lost. Submission stores only a non-authoritative suggestion: AWAITING_HUMAN means no Core Goal has been accepted and no worker/model has started. The human operator reviews the full proposal/hash in Dashboard and explicitly forwards it through the original Core Draft service. This is not approval.

Use `rlflow client status --request <request_id>` or `rlflow client report --request <request_id>`. Report ADOPTED only when the server proves the original Core DRAFT receipt; DRAFT remains unapproved and non-executable. UNKNOWN is unresolved, not success. STALE means the frozen command was not accepted; require a fresh explicit proposal rather than auto-rebasing or changing an unknown command's key. Do not loop on unchanged failures.

Pause and STOP requests are not yet implemented in this client. Report that gap; do not substitute legacy CLI pause/stop, human approval endpoints, shell process killing, or paid model/GPU execution. Natural-language invocation itself is not authorization.
