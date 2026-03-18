"""
Claude Code hook interface.

Implements the PreToolUse hook protocol for Claude Code.
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomli
except ImportError:
    import tomllib as tomli  # Python 3.11+

from .judge import JudgeConfig, JudgeError, evaluate as judge_evaluate
from .logger import log_decision
from .matcher import Matcher, Decision


@dataclass
class HookInput:
    """Input from Claude Code hook system."""
    session_id: str
    transcript_path: str
    cwd: str
    hook_event_name: str
    tool_name: str
    tool_input: dict[str, Any]

    @classmethod
    def from_stdin(cls) -> "HookInput":
        """Read hook input from stdin."""
        data = json.load(sys.stdin)
        return cls(
            session_id=data.get("session_id", ""),
            transcript_path=data.get("transcript_path", ""),
            cwd=data.get("cwd", ""),
            hook_event_name=data.get("hook_event_name", ""),
            tool_name=data.get("tool_name", ""),
            tool_input=data.get("tool_input", {}),
        )

    def get_command(self) -> str | None:
        """Extract command if this is a Bash tool use."""
        if self.tool_name == "Bash":
            return self.tool_input.get("command")
        return None

    def get_file_path(self) -> str | None:
        """Extract file path for Read/Write/Edit tools."""
        if self.tool_name in ("Read", "Write", "Edit", "Glob"):
            return self.tool_input.get("file_path")
        return None


@dataclass
class HookOutput:
    """Output to Claude Code hook system."""
    decision: str  # "allow", "deny", or empty for passthrough
    reason: str

    def write_stdout(self):
        """Write hook output to stdout."""
        if not self.decision:
            # Passthrough - output nothing
            return

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": self.decision,
                "permissionDecisionReason": self.reason,
            },
            "suppressOutput": True
        }
        json.dump(output, sys.stdout)


@dataclass
class Config:
    """Hook configuration."""
    mode: str
    allow_patterns: list[str]
    deny_patterns: list[str]
    judge: JudgeConfig | None = None

    @classmethod
    def load(cls, path: Path) -> "Config":
        """Load config from TOML file."""
        with open(path, "rb") as f:
            data = tomli.load(f)

        settings = data.get("settings", {})
        mode = settings.get("mode", "smart")

        allow_patterns = []
        for rule in data.get("allow", []):
            if "pattern" in rule:
                allow_patterns.append(rule["pattern"])

        deny_patterns = []
        for rule in data.get("deny", []):
            if "pattern" in rule:
                deny_patterns.append(rule["pattern"])

        judge = None
        judge_data = data.get("judge", {})
        if judge_data:
            judge = JudgeConfig(
                enabled=judge_data.get("enabled", False),
                model=judge_data.get("model", "gpt-4o-mini"),
                api_key_env=judge_data.get("api_key_env", "OPENAI_API_KEY"),
                base_url=judge_data.get("base_url", "https://api.openai.com/v1"),
                timeout=judge_data.get("timeout", 5),
            )

        return cls(
            mode=mode,
            allow_patterns=allow_patterns,
            deny_patterns=deny_patterns,
            judge=judge,
        )


def run_hook(config_path: Path):
    """
    Run the permission hook.

    Reads from stdin, writes to stdout per Claude Code protocol.
    """
    # Load config
    config = Config.load(config_path)

    # Read input
    hook_input = HookInput.from_stdin()

    # Only handle Bash commands for now
    if hook_input.tool_name != "Bash":
        # Passthrough for non-Bash tools
        HookOutput(decision="", reason="").write_stdout()
        return

    command = hook_input.get_command()
    if not command:
        HookOutput(decision="", reason="").write_stdout()
        return

    # Create matcher and check
    matcher = Matcher(
        allow_patterns=config.allow_patterns,
        deny_patterns=config.deny_patterns,
        mode=config.mode,
    )

    result = matcher.check(command)

    segments = result.segments_checked or [command]
    judge_decision = None
    judge_reason = None

    if result.decision == Decision.ALLOW:
        log_decision(
            command=command,
            cwd=hook_input.cwd,
            matcher_decision="allow",
            matched_rule=result.matched_rule,
            final_decision="allow",
            segments=segments,
        )
        HookOutput(
            decision="allow",
            reason=result.reason
        ).write_stdout()
    elif result.decision == Decision.DENY:
        log_decision(
            command=command,
            cwd=hook_input.cwd,
            matcher_decision="deny",
            matched_rule=result.matched_rule,
            final_decision="deny",
            segments=segments,
        )
        HookOutput(
            decision="deny",
            reason=result.reason
        ).write_stdout()
    else:
        # ASK = try judge if configured, otherwise passthrough
        final = "passthrough"
        if config.judge and config.judge.enabled:
            try:
                judge_result = judge_evaluate(
                    command=command,
                    segments=segments,
                    config=config.judge,
                    cwd=hook_input.cwd,
                )
                judge_decision = judge_result.decision
                judge_reason = judge_result.reason
                if judge_result.decision == "ALLOW":
                    print(f"Judge approved: {judge_result.reason}", file=sys.stderr)
                    final = "allow"
                    log_decision(
                        command=command,
                        cwd=hook_input.cwd,
                        matcher_decision="ask",
                        matched_rule=result.matched_rule,
                        judge_decision=judge_decision,
                        judge_reason=judge_reason,
                        final_decision="allow",
                        segments=segments,
                    )
                    HookOutput(
                        decision="allow",
                        reason=f"Judge: {judge_result.reason}"
                    ).write_stdout()
                    return
                # Judge DENY = passthrough to human (judge cannot auto-deny)
                print(f"Judge denied, deferring to human: {judge_result.reason}", file=sys.stderr)
            except JudgeError as e:
                print(f"Judge error, falling back to human: {e}", file=sys.stderr)

        log_decision(
            command=command,
            cwd=hook_input.cwd,
            matcher_decision="ask",
            matched_rule=result.matched_rule,
            judge_decision=judge_decision,
            judge_reason=judge_reason,
            final_decision=final,
            segments=segments,
        )
        # Passthrough to normal Claude Code permissions
        HookOutput(decision="", reason="").write_stdout()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", required=True)
    args = parser.parse_args()
    run_hook(Path(args.config))
