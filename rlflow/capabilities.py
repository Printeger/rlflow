"""Non-generating, credential-free runtime compatibility probes.

Protocol declarations are observations, never proof of isolation or paid account
access. No thread/turn, model, job or scheduler is started by this module.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def probe_capabilities(executable="codex", *, pinned_version=None, pinned_protocol_sha256=None, timeout=15):
    report = {
        "adapter": "codex-exec", "version": None, "protocol_sha256": None,
        "compatible": False, "model_access": "UNVERIFIED",
        "structured_output": "UNVERIFIED", "usage": "UNVERIFIED",
        "interrupt": "UNVERIFIED", "resume": "UNVERIFIED",
        "native_subagents": False, "delegation_observability": "UNVERIFIED",
        "enforced_readonly": "UNVERIFIED", "hard_token_limit": False,
        "hard_cost_limit": False, "app_server": "UNVERIFIED",
        "observations": [],
    }
    binary = shutil.which(executable)
    if binary is None:
        report["observations"].append("runtime executable unavailable")
        return report
    with tempfile.TemporaryDirectory(prefix="rlflow-probe-") as directory:
        # Do not load the operator's configuration, plugins or credentials.
        environment = {"PATH": os.environ.get("PATH", ""), "HOME": directory,
                       "CODEX_HOME": directory, "LANG": "C.UTF-8"}
        def run(args):
            result = subprocess.run([binary, *args], env=environment, cwd=directory,
                                    capture_output=True, text=True, timeout=timeout)
            if result.returncode:
                raise ValueError("probe command failed")
            return result.stdout
        try:
            version = run(["--version"]).strip()
            report["version"] = version
            help_text = run(["exec", "--help"])
            report["structured_output"] = "DECLARED" if "--output-schema" in help_text else "UNSUPPORTED"
            report["usage"] = "DECLARED_JSONL" if "--json" in help_text else "UNSUPPORTED"
            report["resume"] = "DECLARED" if "resume" in help_text else "UNSUPPORTED"
            out = Path(directory) / "protocol"
            run(["app-server", "generate-json-schema", "--out", str(out)])
            digest = hashlib.sha256()
            count = 0
            for path in sorted(out.rglob("*.json")):
                content = path.read_bytes()
                json.loads(content)
                digest.update(str(path.relative_to(out)).encode() + b"\0" + content)
                count += 1
            if not count:
                raise ValueError("no generated protocol schemas")
            report["protocol_sha256"] = digest.hexdigest()
            report["app_server"] = "SCHEMA_GENERATED"
            report["observations"].append(f"{count} local protocol schema files generated without model calls")
            # Compatibility means explicitly pinned declarations, not execution approval.
            report["compatible"] = (pinned_version is not None and version == pinned_version
                                    and pinned_protocol_sha256 is not None
                                    and report["protocol_sha256"] == pinned_protocol_sha256)
            report["observations"].append("execution, account access, interrupt and isolation remain unverified")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            report["observations"].append("local protocol probe failed or timed out; execution disabled")
    return report


def resource_capabilities(root=Path("/sys/fs/cgroup")):
    root = Path(root)
    controllers = root / "cgroup.controllers"
    declared = controllers.read_text().split() if controllers.is_file() else []
    # Writable root does not prove a delegated subtree. Runtime must enforce and
    # verify its own per-task group before admitting a strict task.
    return {"cgroup_version": 2 if controllers.is_file() else None,
            "controllers": sorted(declared), "resource_enforcement": "partial",
            "strict_execution_admissible": False,
            "delegation_verified": False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", default="codex")
    parser.add_argument("--pinned-version")
    parser.add_argument("--pinned-protocol-sha256")
    args = parser.parse_args()
    print(json.dumps({"runtime": probe_capabilities(args.executable, pinned_version=args.pinned_version,
                                                    pinned_protocol_sha256=args.pinned_protocol_sha256),
                      "resources": resource_capabilities()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
