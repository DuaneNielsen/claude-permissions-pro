"""
Decision logger for Claude Permissions Pro.

Logs every hook decision to a JSONL file for confusion matrix analysis.
Each line records: timestamp, command, matcher decision, judge decision (if any),
and matched rule.
"""

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from pathlib import Path


DEFAULT_LOG_DIR = Path.home() / ".claude" / "permissions-pro"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "decisions.jsonl"


@dataclass
class DecisionRecord:
    """A single logged decision."""
    timestamp: str
    command: str
    cwd: str
    matcher_decision: str  # allow, deny, ask
    matched_rule: str | None
    judge_decision: str | None  # ALLOW, DENY, or None
    judge_reason: str | None
    final_decision: str  # allow, deny, passthrough
    segments: list[str] | None

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> "DecisionRecord":
        data = json.loads(line)
        return cls(**data)


def log_decision(
    command: str,
    cwd: str,
    matcher_decision: str,
    matched_rule: str | None = None,
    judge_decision: str | None = None,
    judge_reason: str | None = None,
    final_decision: str = "passthrough",
    segments: list[str] | None = None,
    log_file: Path | None = None,
):
    """Append a decision record to the log file."""
    log_file = log_file or DEFAULT_LOG_FILE
    log_file.parent.mkdir(parents=True, exist_ok=True)

    record = DecisionRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        command=command,
        cwd=cwd,
        matcher_decision=matcher_decision,
        matched_rule=matched_rule,
        judge_decision=judge_decision,
        judge_reason=judge_reason,
        final_decision=final_decision,
        segments=segments,
    )

    with open(log_file, "a") as f:
        f.write(record.to_json() + "\n")


def iter_decisions(log_file: Path | None = None):
    """Iterate over all logged decisions."""
    log_file = log_file or DEFAULT_LOG_FILE
    if not log_file.exists():
        return

    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if line:
                yield DecisionRecord.from_json(line)
