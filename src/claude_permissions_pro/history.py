"""
Session history analyzer for Claude Code.

Reads session logs and extracts commands to suggest permission patterns.
"""

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .shell_parser import parse_command, extract_base_command


@dataclass
class CommandRecord:
    """A command extracted from session history."""
    command: str
    session_id: str
    timestamp: datetime | None
    project_path: str | None
    was_allowed: bool | None  # If we can determine from logs


@dataclass
class PatternSuggestion:
    """A suggested permission pattern."""
    pattern: str
    example_commands: list[str]
    frequency: int
    confidence: float  # 0-1, how confident we are this is safe


@dataclass
class HistoryAnalysis:
    """Results of analyzing session history."""
    total_commands: int
    unique_base_commands: Counter
    suggested_patterns: list[PatternSuggestion]
    chained_commands: list[str]  # Commands with &&, ||, etc.


def find_session_dirs() -> list[Path]:
    """Find all Claude Code session directories."""
    claude_dir = Path.home() / ".claude"
    projects_dir = claude_dir / "projects"

    if not projects_dir.exists():
        return []

    session_dirs = []
    for project_dir in projects_dir.iterdir():
        if project_dir.is_dir():
            session_dirs.append(project_dir)

    return session_dirs


def iter_session_files(session_dir: Path) -> Iterator[Path]:
    """Iterate over session JSONL files in a directory."""
    for f in session_dir.iterdir():
        if f.suffix == ".jsonl" and not f.name.startswith("sessions-"):
            yield f


def extract_commands_from_session(session_file: Path) -> Iterator[CommandRecord]:
    """
    Extract Bash commands from a session JSONL file.

    Session files contain JSON lines with various event types.
    We look for tool_use events with tool_name "Bash".
    """
    session_id = session_file.stem
    project_path = session_file.parent.name

    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Look for bash commands in various formats
                command = _extract_command(data)
                if command:
                    yield CommandRecord(
                        command=command,
                        session_id=session_id,
                        timestamp=_parse_timestamp(data),
                        project_path=project_path,
                        was_allowed=None
                    )
    except (IOError, OSError):
        pass


def _extract_command(data: dict) -> str | None:
    """Extract a bash command from a session log entry."""
    # Format 1: Claude Code session format - message.content[].tool_use
    # {"message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "..."}}]}}
    message = data.get("message", {})
    if isinstance(message, dict):
        content = message.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_use" and block.get("name") == "Bash":
                        inp = block.get("input", {})
                        if isinstance(inp, dict):
                            return inp.get("command")

    # Format 2: Direct tool_use at top level
    if data.get("type") == "tool_use" and data.get("tool_name") == "Bash":
        tool_input = data.get("tool_input", {})
        if isinstance(tool_input, dict):
            return tool_input.get("command")

    # Format 3: Content at top level (older format)
    if "content" in data and isinstance(data["content"], list):
        for block in data["content"]:
            if isinstance(block, dict):
                if block.get("type") == "tool_use" and block.get("name") == "Bash":
                    inp = block.get("input", {})
                    if isinstance(inp, dict):
                        return inp.get("command")

    # Format 4: Direct role at top level
    if data.get("role") == "assistant":
        content = data.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    if item.get("name") == "Bash":
                        inp = item.get("input", {})
                        return inp.get("command") if isinstance(inp, dict) else None

    return None


def _parse_timestamp(data: dict) -> datetime | None:
    """Try to extract a timestamp from log data."""
    for key in ("timestamp", "created_at", "time"):
        if key in data:
            try:
                ts = data[key]
                if isinstance(ts, (int, float)):
                    return datetime.fromtimestamp(ts)
                if isinstance(ts, str):
                    # Try ISO format
                    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, OSError):
                pass
    return None


def analyze_history(
    max_sessions: int | None = None,
    min_frequency: int = 2
) -> HistoryAnalysis:
    """
    Analyze Claude Code session history and suggest patterns.

    Args:
        max_sessions: Maximum number of sessions to analyze (None = all)
        min_frequency: Minimum times a command pattern must appear

    Returns:
        HistoryAnalysis with patterns and statistics
    """
    all_commands: list[CommandRecord] = []
    base_command_counter: Counter = Counter()
    full_command_counter: Counter = Counter()
    chained_commands: list[str] = []

    session_dirs = find_session_dirs()
    sessions_analyzed = 0

    for session_dir in session_dirs:
        for session_file in iter_session_files(session_dir):
            if max_sessions and sessions_analyzed >= max_sessions:
                break

            for record in extract_commands_from_session(session_file):
                all_commands.append(record)
                cmd = record.command

                # Parse and analyze
                parsed = parse_command(cmd)
                if not parsed.is_simple:
                    chained_commands.append(cmd)

                # Count base commands and full patterns
                for seg in parsed.segments:
                    base = extract_base_command(seg.command)
                    base_command_counter[base] += 1
                    full_command_counter[seg.command] += 1

            sessions_analyzed += 1

    # Generate pattern suggestions
    suggestions = _generate_suggestions(
        base_command_counter,
        full_command_counter,
        min_frequency
    )

    return HistoryAnalysis(
        total_commands=len(all_commands),
        unique_base_commands=base_command_counter,
        suggested_patterns=suggestions,
        chained_commands=chained_commands[:50]  # Limit for display
    )


def _generate_suggestions(
    base_commands: Counter,
    full_commands: Counter,
    min_frequency: int
) -> list[PatternSuggestion]:
    """Generate pattern suggestions from command frequency data."""
    suggestions = []

    # Well-known safe command patterns
    SAFE_PATTERNS = {
        "git": ["git *"],
        "npm": ["npm *"],
        "yarn": ["yarn *"],
        "pnpm": ["pnpm *"],
        "cargo": ["cargo *"],
        "make": ["make *"],
        "just": ["just *"],
        "python": ["python *", "python3 *"],
        "pip": ["pip *", "pip3 *"],
        "poetry": ["poetry *"],
        "go": ["go *"],
        "rustc": ["rustc *"],
        "node": ["node *"],
        "deno": ["deno *"],
        "bun": ["bun *"],
        "docker": ["docker *"],
        "kubectl": ["kubectl *"],
        "ls": ["ls *"],
        "cat": ["cat *"],
        "head": ["head *"],
        "tail": ["tail *"],
        "grep": ["grep *"],
        "find": ["find *"],
        "rg": ["rg *"],
        "fd": ["fd *"],
        "tree": ["tree *"],
        "pwd": ["pwd"],
        "which": ["which *"],
        "echo": ["echo *"],
        "env": ["env"],
        "printenv": ["printenv *"],
    }

    # Generate suggestions based on frequency
    for base_cmd, count in base_commands.most_common(50):
        if count < min_frequency:
            continue

        # Get example commands
        examples = [
            cmd for cmd, _ in full_commands.most_common(100)
            if extract_base_command(cmd) == base_cmd
        ][:5]

        # Determine pattern and confidence
        if base_cmd in SAFE_PATTERNS:
            patterns = SAFE_PATTERNS[base_cmd]
            confidence = 0.9
        else:
            patterns = [f"{base_cmd} *"]
            confidence = 0.5  # Unknown command, lower confidence

        for pattern in patterns:
            suggestions.append(PatternSuggestion(
                pattern=pattern,
                example_commands=examples,
                frequency=count,
                confidence=confidence
            ))

    # Sort by frequency * confidence
    suggestions.sort(key=lambda s: s.frequency * s.confidence, reverse=True)

    return suggestions


def export_suggested_config(analysis: HistoryAnalysis, min_confidence: float = 0.7) -> str:
    """Generate a TOML config from analysis results."""
    lines = [
        "# Auto-generated by claude-permissions-pro",
        "# Based on analysis of your Claude Code session history",
        "",
        "[settings]",
        'mode = "smart"  # Parse chains, allow if all segments match',
        "",
        "# Allow patterns (generated from your history)",
    ]

    seen_patterns = set()
    for suggestion in analysis.suggested_patterns:
        if suggestion.confidence >= min_confidence and suggestion.pattern not in seen_patterns:
            seen_patterns.add(suggestion.pattern)
            lines.append("")
            lines.append(f"# Used {suggestion.frequency} times")
            lines.append(f"# Examples: {suggestion.example_commands[:3]}")
            lines.append("[[allow]]")
            lines.append(f'pattern = "{suggestion.pattern}"')

    # Add common deny patterns
    lines.extend([
        "",
        "# Deny patterns (safety defaults)",
        "",
        "[[deny]]",
        'pattern = "rm -rf *"',
        "",
        "[[deny]]",
        'pattern = "sudo *"',
        "",
        "[[deny]]",
        'pattern = "chmod 777 *"',
    ])

    return "\n".join(lines)
