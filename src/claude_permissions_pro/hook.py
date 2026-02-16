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

        return cls(
            mode=mode,
            allow_patterns=allow_patterns,
            deny_patterns=deny_patterns,
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

    if result.decision == Decision.ALLOW:
        HookOutput(
            decision="allow",
            reason=result.reason
        ).write_stdout()
    elif result.decision == Decision.DENY:
        HookOutput(
            decision="deny",
            reason=result.reason
        ).write_stdout()
    else:
        # ASK = passthrough to normal Claude Code permissions
        HookOutput(decision="", reason="").write_stdout()
