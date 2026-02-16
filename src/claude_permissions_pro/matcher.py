"""
Pattern matching for shell commands.

Supports glob-style patterns and checks each segment of chained commands.
"""

import fnmatch
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .shell_parser import ParsedCommand, parse_command, extract_base_command


class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # Passthrough to user


@dataclass
class MatchResult:
    """Result of matching a command against rules."""
    decision: Decision
    reason: str
    matched_rule: str | None = None
    segments_checked: list[str] | None = None


@dataclass
class Pattern:
    """A permission pattern."""
    raw: str                    # Original pattern string
    is_regex: bool              # True if regex, False if glob
    compiled: re.Pattern | None # Compiled regex or None for glob
    base_command: str | None    # If pattern starts with a command name

    @classmethod
    def from_string(cls, pattern: str) -> "Pattern":
        """
        Parse a pattern string.

        Patterns can be:
        - Glob: "npm *", "git commit *"
        - Regex: "/^npm (install|test|run).*/"
        - Base command only: "npm" (matches any npm command)
        """
        if pattern.startswith("/") and pattern.endswith("/"):
            # Regex pattern
            regex_str = pattern[1:-1]
            return cls(
                raw=pattern,
                is_regex=True,
                compiled=re.compile(regex_str),
                base_command=None
            )

        # Glob pattern - extract base command
        base = pattern.split()[0] if pattern.split() else pattern
        # Remove trailing * for base command matching
        base = base.rstrip("*").strip()

        return cls(
            raw=pattern,
            is_regex=False,
            compiled=None,
            base_command=base if base else None
        )

    def matches(self, command: str) -> bool:
        """Check if a command matches this pattern."""
        command = command.strip()

        # Normalize: strip ./ prefix for matching
        if command.startswith("./"):
            command = command[2:]

        # Normalize: replace path-based commands with just the binary name
        # e.g., ".venv/bin/python foo" -> "python foo"
        # e.g., "/usr/bin/node script.js" -> "node script.js"
        parts = command.split(maxsplit=1)
        if parts and '/' in parts[0]:
            binary = parts[0].rsplit('/', 1)[-1]
            command = binary + (' ' + parts[1] if len(parts) > 1 else '')

        if self.is_regex and self.compiled:
            return bool(self.compiled.search(command))

        # Glob matching
        return fnmatch.fnmatch(command, self.raw)


@dataclass
class Rule:
    """A permission rule."""
    patterns: list[Pattern]
    decision: Decision

    def matches(self, command: str) -> Pattern | None:
        """Return the first matching pattern, or None."""
        for p in self.patterns:
            if p.matches(command):
                return p
        return None


class Matcher:
    """
    Matches commands against allow/deny rules.

    Key feature: Parses chained commands and checks EACH segment.
    """

    def __init__(
        self,
        allow_patterns: list[str],
        deny_patterns: list[str] | None = None,
        mode: str = "smart"
    ):
        """
        Initialize the matcher.

        Args:
            allow_patterns: Patterns for commands to allow
            deny_patterns: Patterns for commands to deny (checked first)
            mode: One of "smart", "paranoid", "yolo"
                - smart: Parse chains, allow if all segments match
                - paranoid: Block any chain with unknown segments
                - yolo: Allow chains if ANY segment matches
        """
        self.allow_rules = [
            Rule(patterns=[Pattern.from_string(p)], decision=Decision.ALLOW)
            for p in allow_patterns
        ]
        self.deny_rules = [
            Rule(patterns=[Pattern.from_string(p)], decision=Decision.DENY)
            for p in (deny_patterns or [])
        ]
        self.mode = mode

    def check(self, command: str) -> MatchResult:
        """
        Check if a command should be allowed.

        For chained commands, parses and checks each segment.
        """
        parsed = parse_command(command)

        # First check deny rules against the whole command
        for rule in self.deny_rules:
            if pattern := rule.matches(command):
                return MatchResult(
                    decision=Decision.DENY,
                    reason=f"Matches deny pattern: {pattern.raw}",
                    matched_rule=pattern.raw
                )

        # For simple commands, just check allow rules
        if parsed.is_simple and len(parsed.segments) == 1:
            return self._check_single(parsed.segments[0].command)

        # For chains, check each segment
        return self._check_chain(parsed)

    def _check_single(self, command: str) -> MatchResult:
        """Check a single command (no chains)."""
        for rule in self.deny_rules:
            if pattern := rule.matches(command):
                return MatchResult(
                    decision=Decision.DENY,
                    reason=f"Matches deny pattern: {pattern.raw}",
                    matched_rule=pattern.raw
                )

        for rule in self.allow_rules:
            if pattern := rule.matches(command):
                return MatchResult(
                    decision=Decision.ALLOW,
                    reason=f"Matches allow pattern: {pattern.raw}",
                    matched_rule=pattern.raw
                )

        return MatchResult(
            decision=Decision.ASK,
            reason="No matching rule"
        )

    def _check_chain(self, parsed: ParsedCommand) -> MatchResult:
        """Check a chained command."""
        segments = [s.command for s in parsed.segments]
        results = []

        for seg in segments:
            result = self._check_single(seg)
            results.append((seg, result))

            # If any segment is denied, deny the whole chain
            if result.decision == Decision.DENY:
                return MatchResult(
                    decision=Decision.DENY,
                    reason=f"Segment '{seg}' denied: {result.reason}",
                    matched_rule=result.matched_rule,
                    segments_checked=segments
                )

        # Count allowed vs unknown
        allowed = [r for r in results if r[1].decision == Decision.ALLOW]
        unknown = [r for r in results if r[1].decision == Decision.ASK]

        if self.mode == "smart":
            # All segments must be allowed
            if len(allowed) == len(results):
                return MatchResult(
                    decision=Decision.ALLOW,
                    reason=f"All {len(segments)} segments match allow patterns",
                    segments_checked=segments
                )
            else:
                unknown_cmds = [r[0] for r in unknown]
                return MatchResult(
                    decision=Decision.ASK,
                    reason=f"Unknown segments: {unknown_cmds}",
                    segments_checked=segments
                )

        elif self.mode == "yolo":
            # Any allowed segment = allow whole chain
            if allowed:
                return MatchResult(
                    decision=Decision.ALLOW,
                    reason=f"{len(allowed)}/{len(segments)} segments matched",
                    segments_checked=segments
                )
            return MatchResult(
                decision=Decision.ASK,
                reason="No segments matched allow patterns",
                segments_checked=segments
            )

        else:  # paranoid
            # Any unknown = ask
            if unknown:
                return MatchResult(
                    decision=Decision.ASK,
                    reason=f"Unknown segments in chain: {[r[0] for r in unknown]}",
                    segments_checked=segments
                )
            return MatchResult(
                decision=Decision.ALLOW,
                reason="All segments verified",
                segments_checked=segments
            )
