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

    @staticmethod
    def _strip_env_prefixes(command: str) -> str:
        """Strip leading VAR=value assignments, handling quoted values with spaces."""
        while command:
            # Check if command starts with a variable assignment
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=', command)
            if not m:
                break
            # Skip past the VAR= part
            rest = command[m.end():]
            # Parse the value (may be quoted)
            if rest.startswith('"'):
                # Find closing quote
                end = rest.find('"', 1)
                if end == -1:
                    break  # Unterminated quote, bail
                rest = rest[end + 1:]
            elif rest.startswith("'"):
                end = rest.find("'", 1)
                if end == -1:
                    break
                rest = rest[end + 1:]
            else:
                # Unquoted: value extends to next whitespace
                parts = rest.split(maxsplit=1)
                rest = parts[1] if len(parts) > 1 else ''
            rest = rest.lstrip()
            if not rest:
                break  # Bare assignment, nothing after
            command = rest
        return command

    @staticmethod
    def _strip_sudo(command: str) -> str:
        """Strip leading sudo and its flags, leaving the actual command.

        sudo is just privilege escalation — the underlying command determines safety.
        Handles: sudo cmd, sudo -u user cmd, sudo -E cmd, sudo -i cmd, etc.
        """
        if not command.startswith("sudo"):
            return command
        parts = command.split()
        if not parts or parts[0] != "sudo":
            return command
        i = 1
        while i < len(parts):
            arg = parts[i]
            if arg == "--":
                i += 1
                break
            if not arg.startswith("-"):
                break
            # Flags that take an argument: -u user, -g group, -C fd, -D dir
            if arg in ("-u", "-g", "-C", "-D"):
                i += 2  # skip flag + its value
            else:
                i += 1  # skip boolean flag (-E, -i, -n, -s, etc.)
        return " ".join(parts[i:]) if i < len(parts) else command

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

        # Normalize: strip leading env-var assignments (e.g. FOO=bar cmd -> cmd)
        # Handles quoted values like COMPUTE_LEVEL="50 60 70 80 90"
        command = self._strip_env_prefixes(command)

        # Normalize: strip sudo prefix (sudo is just privilege escalation,
        # the actual command determines safety)
        command = self._strip_sudo(command)

        # Normalize: strip ./ prefix for matching
        if command.startswith("./"):
            command = command[2:]

        # Normalize: replace path-based commands with just the binary name
        # e.g., ".venv/bin/python foo" -> "python foo"
        # e.g., "/usr/bin/node script.js" -> "node script.js"
        # But skip redirect segments like ">/tmp/foo.log" or ">/dev/null"
        parts = command.split(maxsplit=1)
        if parts and '/' in parts[0] and not parts[0].startswith('>'):
            binary = parts[0].rsplit('/', 1)[-1]
            command = binary + (' ' + parts[1] if len(parts) > 1 else '')

        if self.is_regex and self.compiled:
            return bool(self.compiled.search(command))

        # Glob matching
        if fnmatch.fnmatch(command, self.raw):
            return True

        # "cmd *" patterns should also match bare "cmd" (no args).
        # Shell keywords like `done`, `do`, `for`, `echo` appear bare as
        # chain segments — without this, they'd cascade to ASK on the
        # whole chain.
        if self.raw.endswith(" *") and command == self.raw[:-2]:
            return True

        return False


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

    @staticmethod
    def _is_bare_assignment(command: str) -> bool:
        """Check if command is a variable assignment (no separate execution).

        Matches: FOO="bar", count=$(cmd), x=$(echo hi | wc -l)
        Does NOT match: FOO=bar cmd (env prefix + command execution)
        """
        if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', command):
            return False
        # Simple assignment: no spaces (FOO="bar", X=1)
        if len(command.split()) == 1:
            return True
        # Compound assignment: value is a subshell like var=$(...)
        # Extract the value part after the first =
        _, _, value = command.partition('=')
        value = value.strip()
        if value.startswith('$(') or value.startswith('`'):
            return True
        return False

    def _check_single(self, command: str) -> MatchResult:
        """Check a single command (no chains)."""
        # Bare variable assignments (e.g., FOO="bar") are safe — no execution
        if self._is_bare_assignment(command):
            return MatchResult(
                decision=Decision.ALLOW,
                reason="Bare variable assignment (no execution)",
            )

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
