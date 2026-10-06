"""Container administrator reconciliation after confirming Docker operations stopped."""

import argparse
import hashlib
import json
import os
import time
from execution_agent.runtime import AgentRuntime
from operations.privacy import redact


def main():
    parser = argparse.ArgumentParser(
        description="Resolve an uncertain local execution after manual inspection"
    )
    parser.add_argument("execution_id")
    parser.add_argument(
        "--observed-status", choices=["success", "failed"], required=True
    )
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--request-file",
        help="Original central agent_body JSON; needed to cancel an execution not yet in the journal",
    )
    parser.add_argument(
        "--confirm-operations-stopped", action="store_true", required=True
    )
    args = parser.parse_args()
    with open(os.environ["EXECUTION_AGENT_MANIFEST"]) as file:
        manifest = json.load(file)
    runtime = AgentRuntime(
        manifest, os.getenv("EXECUTION_AGENT_JOURNAL", "agent-state/executions.sqlite")
    )
    with runtime.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT result FROM executions WHERE id=?", (args.execution_id,)
        ).fetchone()
        if not row:
            if not args.request_file or args.observed_status != "failed":
                raise SystemExit(
                    "Missing journal: provide --request-file and --observed-status failed to create a cancellation tombstone"
                )
            with open(args.request_file) as file:
                body = json.load(file)
            if (
                body.get("execution_id") != args.execution_id
                or body.get("target") != runtime.identity()
            ):
                raise SystemExit("Original execution request identity mismatch")
            result = {
                "execution_id": args.execution_id,
                "target": runtime.identity(),
                "status": "unknown",
                "script_id": body["script_id"],
                "policy_digest": body["policy_digest"],
            }
            fingerprint = hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()
            ).hexdigest()
            db.execute(
                "INSERT INTO executions VALUES (?,?,?)",
                (args.execution_id, fingerprint, json.dumps(result)),
            )
        else:
            result = json.loads(row[0])
        if result.get("status") not in {"running", "unknown", "rollback_failed"}:
            raise SystemExit("Only unresolved executions can be reconciled")
        result.update(
            status=args.observed_status,
            manually_reconciled=True,
            reconciliation_reason=redact(args.reason),
            finished_at=time.time(),
        )
        db.execute(
            "UPDATE executions SET result=? WHERE id=?",
            (json.dumps(result), args.execution_id),
        )
        db.execute("DELETE FROM active WHERE execution_id=?", (args.execution_id,))
    print(
        "Journal reconciled. Refresh the central execution result; business checks remain required for success."
    )


if __name__ == "__main__":
    main()
