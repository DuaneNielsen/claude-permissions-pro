"""
Confusion matrix analysis for permission rules.

Compares your config/judge decisions against ground truth (your actual history)
to compute precision, recall, F1, and identify coverage gaps.

Ground truth sources:
- Session history: commands that were executed = user approved them
- Decision log: records matcher/judge decisions for every hook invocation

Classification (from the perspective of "should this be auto-approved?"):
- TP: config says ALLOW, and it was a command you actually use (correct auto-approve)
- FN: config says ASK/DENY, but you approved it anyway (missed coverage)
- FP: config says ALLOW, but you wouldn't have approved it (risky auto-approve)
  (requires decision log + negative examples, can't be derived from history alone)
- TN: config says ASK/DENY, and it genuinely shouldn't run (correct block)
  (also requires negative examples)

With history alone we get TP and FN → recall.
With the decision log we can also track FP over time.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .history import (
    find_session_dirs,
    iter_session_files,
    extract_commands_from_session,
)
from .logger import iter_decisions, DecisionRecord
from .matcher import Matcher, Decision


@dataclass
class ConfusionResult:
    """Results of confusion matrix analysis."""
    # Core counts
    true_positives: int = 0   # ALLOW and user approved (in history)
    false_negatives: int = 0  # ASK/DENY but user approved (in history)
    # These require decision log data
    passthrough_count: int = 0  # Commands that went to human review
    judge_overrides: int = 0    # Judge said DENY, went to human

    # Derived metrics
    total_commands: int = 0
    unique_commands: int = 0

    # Breakdown of false negatives by base command
    fn_by_command: Counter = field(default_factory=Counter)
    # Commands the judge denied but user presumably approved
    judge_denied_commands: list[str] = field(default_factory=list)
    # Sample TP commands for sanity checking
    tp_samples: list[str] = field(default_factory=list)
    # Sample FN commands
    fn_samples: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        """What fraction of user-approved commands would be auto-approved."""
        total = self.true_positives + self.false_negatives
        return self.true_positives / total if total > 0 else 0.0

    @property
    def auto_approve_rate(self) -> float:
        """Alias for recall — more intuitive name."""
        return self.recall

    @property
    def manual_review_rate(self) -> float:
        """What fraction would require manual review."""
        return 1.0 - self.recall

    def format_report(self) -> str:
        """Format a human-readable report."""
        lines = []
        lines.append("=" * 60)
        lines.append("CONFUSION MATRIX ANALYSIS")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"Total commands analyzed: {self.total_commands}")
        lines.append(f"Unique commands:         {self.unique_commands}")
        lines.append("")
        lines.append("--- Classification ---")
        lines.append(f"True Positives (auto-approved, correct): {self.true_positives}")
        lines.append(f"False Negatives (would need manual OK):  {self.false_negatives}")
        lines.append("")
        lines.append("--- Metrics ---")
        lines.append(f"Recall (auto-approve rate): {self.recall:.1%}")
        lines.append(f"Manual review rate:         {self.manual_review_rate:.1%}")
        lines.append("")

        if self.fn_by_command:
            lines.append("--- Top uncovered commands (false negatives) ---")
            for cmd, count in self.fn_by_command.most_common(20):
                lines.append(f"  {cmd}: {count}")
            lines.append("")

        if self.fn_samples:
            lines.append("--- Sample false negatives (commands you'd have to manually approve) ---")
            for cmd in self.fn_samples[:10]:
                lines.append(f"  {cmd[:100]}")
            lines.append("")

        if self.judge_denied_commands:
            lines.append("--- Judge denied (user overrides) ---")
            for cmd in self.judge_denied_commands[:10]:
                lines.append(f"  {cmd[:100]}")
            lines.append("")

        if self.passthrough_count > 0:
            lines.append("--- Decision log stats ---")
            lines.append(f"Total passthrough to human: {self.passthrough_count}")
            lines.append(f"Judge denied → human:       {self.judge_overrides}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)


def analyze_from_history(
    matcher: Matcher,
    max_sessions: int | None = None,
) -> ConfusionResult:
    """
    Run confusion matrix analysis using session history as ground truth.

    Every command in history was executed → user approved it.
    We check what the matcher would have decided for each one.
    """
    result = ConfusionResult()
    seen_commands: set[str] = set()

    session_dirs = find_session_dirs()
    sessions_analyzed = 0

    for session_dir in session_dirs:
        for session_file in iter_session_files(session_dir):
            if max_sessions and sessions_analyzed >= max_sessions:
                break

            for record in extract_commands_from_session(session_file):
                result.total_commands += 1
                cmd = record.command

                # Deduplicate for unique count
                if cmd in seen_commands:
                    continue
                seen_commands.add(cmd)
                result.unique_commands += 1

                # What would the matcher decide?
                match_result = matcher.check(cmd)

                if match_result.decision == Decision.ALLOW:
                    result.true_positives += 1
                    if len(result.tp_samples) < 20:
                        result.tp_samples.append(cmd)
                else:
                    # ASK or DENY — user approved it but config wouldn't auto-approve
                    result.false_negatives += 1
                    if len(result.fn_samples) < 50:
                        result.fn_samples.append(cmd)

                    # Track base command for FN breakdown
                    base = cmd.split()[0] if cmd.split() else cmd
                    result.fn_by_command[base] += 1

            sessions_analyzed += 1

    return result


def analyze_from_log(
    log_file: Path | None = None,
) -> ConfusionResult:
    """
    Analyze the decision log for override patterns.

    Looks for commands where the hook passed through to human review
    (the user was prompted). Since those commands then executed,
    the user approved them — these are false negatives / overrides.
    """
    result = ConfusionResult()

    for record in iter_decisions(log_file):
        result.total_commands += 1

        if record.final_decision == "allow":
            result.true_positives += 1
        elif record.final_decision == "passthrough":
            result.passthrough_count += 1
            result.false_negatives += 1
            if len(result.fn_samples) < 50:
                result.fn_samples.append(record.command)

            base = record.command.split()[0] if record.command.split() else record.command
            result.fn_by_command[base] += 1

            if record.judge_decision == "DENY":
                result.judge_overrides += 1
                result.judge_denied_commands.append(record.command)
        elif record.final_decision == "deny":
            # Actually blocked — this is a true negative (or false positive
            # if the user would have wanted it). We count it but can't
            # classify without knowing user intent.
            pass

    result.unique_commands = result.total_commands  # log entries are already per-invocation
    return result
