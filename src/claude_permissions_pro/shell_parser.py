"""
Shell command parser that understands chains, pipes, and subshells.

Unlike naive regex approaches, this actually parses the command structure
and extracts individual commands for evaluation.
"""

import re
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Iterator


class Operator(Enum):
    """Shell operators that chain commands."""
    AND = "&&"      # Run next if previous succeeds
    OR = "||"       # Run next if previous fails
    SEMI = ";"      # Run sequentially regardless
    PIPE = "|"      # Pipe stdout to stdin
    BG = "&"        # Run in background (single &)


@dataclass
class CommandSegment:
    """A single command segment in a chain."""
    command: str           # The raw command string
    operator_before: Operator | None  # Operator connecting to previous command
    has_subshell: bool     # Contains $() or backticks
    has_redirect: bool     # Contains >, <, >>


@dataclass
class ParsedCommand:
    """Result of parsing a shell command."""
    original: str
    segments: list[CommandSegment]
    is_simple: bool        # Single command, no chains/pipes

    def iter_commands(self) -> Iterator[str]:
        """Iterate over just the command strings."""
        for seg in self.segments:
            yield seg.command


def parse_command(cmd: str) -> ParsedCommand:
    """
    Parse a shell command into segments.

    Handles:
    - && (AND chains)
    - || (OR chains)
    - ; (sequential)
    - | (pipes)
    - Respects quoted strings
    - Detects subshells and redirects

    Examples:
        >>> p = parse_command("npm install && npm test")
        >>> list(p.iter_commands())
        ['npm install', 'npm test']

        >>> p = parse_command("echo 'hello && world'")
        >>> p.is_simple
        True  # && is inside quotes, not an operator
    """
    segments = []
    current_cmd = ""
    current_op = None

    # Track quote state
    in_single_quote = False
    in_double_quote = False
    escape_next = False

    # Track subshell depth
    paren_depth = 0
    in_backtick = False

    # Track heredoc state
    heredoc_delim = None       # The delimiter we're looking for
    heredoc_started = False    # True once we've passed the first newline after <<

    i = 0
    while i < len(cmd):
        char = cmd[i]

        # Heredoc body: consume everything until delimiter on its own line
        if heredoc_delim is not None:
            if char == '\n':
                current_cmd += char
                i += 1
                if not heredoc_started:
                    heredoc_started = True
                    continue
                # Check if the next line matches the delimiter
                line_end = cmd.find('\n', i)
                if line_end == -1:
                    line_end = len(cmd)
                line = cmd[i:line_end].strip()
                if line == heredoc_delim:
                    # Consume the delimiter line
                    current_cmd += cmd[i:line_end]
                    i = line_end
                    heredoc_delim = None
                    heredoc_started = False
                continue
            current_cmd += char
            i += 1
            continue

        # Handle escape sequences
        if escape_next:
            current_cmd += char
            escape_next = False
            i += 1
            continue

        if char == '\\' and not in_single_quote:
            escape_next = True
            current_cmd += char
            i += 1
            continue

        # Handle quotes
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current_cmd += char
            i += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current_cmd += char
            i += 1
            continue

        # Skip operator detection inside quotes
        if in_single_quote or in_double_quote:
            current_cmd += char
            i += 1
            continue

        # Track subshells $()
        if char == '$' and i + 1 < len(cmd) and cmd[i + 1] == '(':
            paren_depth += 1
            current_cmd += '$('
            i += 2  # Consume both $ and ( to avoid double-counting
            continue

        if char == '(' and paren_depth > 0:
            paren_depth += 1
            current_cmd += char
            i += 1
            continue

        if char == ')' and paren_depth > 0:
            paren_depth -= 1
            current_cmd += char
            i += 1
            continue

        # Track backticks
        if char == '`':
            in_backtick = not in_backtick
            current_cmd += char
            i += 1
            continue

        # Skip operator detection inside subshells
        if paren_depth > 0 or in_backtick:
            current_cmd += char
            i += 1
            continue

        # Detect heredoc: << DELIM or <<'DELIM' or <<"DELIM" or <<-DELIM
        two_char = cmd[i:i+2] if i + 1 < len(cmd) else ""
        if two_char == "<<" and (i + 2 >= len(cmd) or cmd[i + 2] != '<'):
            current_cmd += "<<"
            j = i + 2
            # Skip optional - (for <<-)
            if j < len(cmd) and cmd[j] == '-':
                current_cmd += '-'
                j += 1
            # Skip whitespace between << and delimiter
            while j < len(cmd) and cmd[j] in ' \t':
                current_cmd += cmd[j]
                j += 1
            # Extract delimiter (possibly quoted)
            if j < len(cmd):
                quote_char = None
                if cmd[j] in ("'", '"'):
                    quote_char = cmd[j]
                    current_cmd += cmd[j]
                    j += 1
                delim_start = j
                while j < len(cmd) and cmd[j] not in ('\n', ' ', '\t', ';'):
                    if quote_char and cmd[j] == quote_char:
                        break
                    j += 1
                heredoc_delim = cmd[delim_start:j]
                current_cmd += cmd[delim_start:j]
                if quote_char and j < len(cmd) and cmd[j] == quote_char:
                    current_cmd += cmd[j]
                    j += 1
                heredoc_started = False
            i = j
            continue

        # Check for two-character operators
        if two_char == "&&":
            _flush_segment(segments, current_cmd, current_op)
            current_cmd = ""
            current_op = Operator.AND
            i += 2
            continue

        if two_char == "||":
            _flush_segment(segments, current_cmd, current_op)
            current_cmd = ""
            current_op = Operator.OR
            i += 2
            continue

        # Single character operators
        if char == ";" or char == "\n":
            _flush_segment(segments, current_cmd, current_op)
            current_cmd = ""
            current_op = Operator.SEMI
            i += 1
            continue

        if char == "|":
            _flush_segment(segments, current_cmd, current_op)
            current_cmd = ""
            current_op = Operator.PIPE
            i += 1
            continue

        # Background operator (single &, not && and not part of redirect like 2>&1)
        if char == "&" and (i + 1 >= len(cmd) or cmd[i + 1] != "&"):
            # Check if this is part of a redirect pattern
            is_redirect = False

            # Forward-looking: &> or &>> (bash redirect stdout+stderr)
            if i + 1 < len(cmd) and cmd[i + 1] == '>':
                is_redirect = True

            # Backward-looking: >&N or N>&N patterns (e.g. 2>&1)
            if not is_redirect and i > 0:
                prev_char = cmd[i - 1]
                if prev_char == '>':
                    is_redirect = True
                elif prev_char.isdigit() and i >= 2 and cmd[i - 2] == '>':
                    is_redirect = True

            if not is_redirect:
                _flush_segment(segments, current_cmd, current_op)
                current_cmd = ""
                current_op = Operator.BG
                i += 1
                continue

        current_cmd += char
        i += 1

    # Flush final segment
    _flush_segment(segments, current_cmd, current_op)

    return ParsedCommand(
        original=cmd,
        segments=segments,
        is_simple=len(segments) <= 1 and not any(s.has_subshell for s in segments)
    )


def _flush_segment(segments: list[CommandSegment], cmd: str, op: Operator | None):
    """Add a command segment to the list."""
    cmd = cmd.strip()
    if not cmd:
        return

    has_subshell = "$(" in cmd or "`" in cmd
    has_redirect = bool(re.search(r'[<>]', cmd))

    segments.append(CommandSegment(
        command=cmd,
        operator_before=op,
        has_subshell=has_subshell,
        has_redirect=has_redirect,
    ))


def extract_base_command(cmd: str) -> str:
    """
    Extract the base command (executable name) from a command string.

    Examples:
        >>> extract_base_command("npm install --save foo")
        'npm'
        >>> extract_base_command("NODE_ENV=prod npm test")
        'npm'
        >>> extract_base_command("/usr/bin/python3 script.py")
        'python3'
    """
    cmd = cmd.strip()

    # Skip leading env var assignments
    while '=' in cmd.split()[0] if cmd.split() else False:
        parts = cmd.split(maxsplit=1)
        if len(parts) > 1:
            cmd = parts[1]
        else:
            break

    # Get first token
    try:
        tokens = shlex.split(cmd)
        if tokens:
            # Get basename if it's a path
            base = tokens[0].split('/')[-1]
            return base
    except ValueError:
        # shlex failed, fall back to simple split
        first = cmd.split()[0] if cmd.split() else cmd
        return first.split('/')[-1]

    return cmd
