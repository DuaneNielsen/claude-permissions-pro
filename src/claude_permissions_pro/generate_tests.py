#!/usr/bin/env python3
"""
Generate test cases from Claude Code session history.

Extracts all approved bash commands and creates pytest tests
to verify the permission system would allow them.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .history import (
    find_session_dirs,
    iter_session_files,
    extract_commands_from_session,
)
from .shell_parser import parse_command, extract_base_command


def extract_all_commands(max_sessions: int | None = None) -> list[str]:
    """Extract all unique bash commands from history."""
    commands = set()
    sessions_processed = 0

    for session_dir in find_session_dirs():
        for session_file in iter_session_files(session_dir):
            if max_sessions and sessions_processed >= max_sessions:
                break

            for record in extract_commands_from_session(session_file):
                if record.command:
                    commands.add(record.command)

            sessions_processed += 1

    return sorted(commands)


def generate_test_file(
    commands: list[str],
    output_path: Path,
    config_path: str = "~/.config/claude-permissions-pro.toml"
) -> int:
    """
    Generate a pytest file that tests all commands.

    Returns number of test cases generated.
    """
    # Commands that should require manual approval (ASK), not auto-allow
    ASK_COMMANDS = {"sudo", "rm"}

    # Group commands by base command for organization
    by_base: dict[str, list[str]] = {}
    for cmd in commands:
        parsed = parse_command(cmd)
        if parsed.segments:
            base = extract_base_command(parsed.segments[0].command)
            by_base.setdefault(base, []).append(cmd)

    lines = [
        '"""',
        'Auto-generated tests from Claude Code session history.',
        '',
        'These are commands you have previously approved.',
        'The permission system should allow all of them.',
        '"""',
        '',
        'import pytest',
        'from pathlib import Path',
        'from claude_permissions_pro.hook import Config',
        'from claude_permissions_pro.matcher import Matcher, Decision',
        '',
        '',
        f'CONFIG_PATH = Path("{config_path}").expanduser()',
        '',
        '',
        '@pytest.fixture(scope="module")',
        'def matcher():',
        '    """Load matcher from config."""',
        '    if not CONFIG_PATH.exists():',
        '        pytest.skip(f"Config not found: {CONFIG_PATH}")',
        '    config = Config.load(CONFIG_PATH)',
        '    return Matcher(',
        '        allow_patterns=config.allow_patterns,',
        '        deny_patterns=config.deny_patterns,',
        '        mode=config.mode,',
        '    )',
        '',
        '',
    ]

    test_count = 0

    # Generate test class per base command
    for base_cmd in sorted(by_base.keys()):
        cmds = by_base[base_cmd]

        # Sanitize class name
        class_name = f"TestApproved_{_sanitize_name(base_cmd)}"

        lines.append(f'class {class_name}:')
        lines.append(f'    """Tests for {base_cmd} commands."""')
        lines.append('')

        for i, cmd in enumerate(cmds[:50]):  # Limit per base command
            test_name = f"test_{_sanitize_name(base_cmd)}_{i}"
            # Escape for Python string literal
            escaped_cmd = (cmd
                .replace('\\', '\\\\')
                .replace('"', '\\"')
                .replace('\n', '\\n')
                .replace('\r', '\\r')
                .replace('\t', '\\t'))

            # Escape docstring (no backslashes that look like escapes)
            doc_cmd = _truncate(cmd, 50).replace('\\', '/').replace('"', "'")

            # Determine expected decision
            if base_cmd in ASK_COMMANDS:
                expected_decision = "Decision.ASK"
                expected_name = "ASK"
            else:
                expected_decision = "Decision.ALLOW"
                expected_name = "ALLOW"

            lines.append(f'    def {test_name}(self, matcher):')
            lines.append(f'        """Test: {doc_cmd}"""')
            lines.append(f'        cmd = "{escaped_cmd}"')
            lines.append(f'        result = matcher.check(cmd)')
            lines.append(f'        assert result.decision == {expected_decision}, \\')
            lines.append(f'            f"Expected {expected_name} for {{cmd!r}}, got {{result.decision}}: {{result.reason}}"')
            lines.append('')

            test_count += 1

        lines.append('')

    output_path.write_text('\n'.join(lines))
    return test_count


def _sanitize_name(s: str) -> str:
    """Convert string to valid Python identifier."""
    s = re.sub(r'[^a-zA-Z0-9]', '_', s)
    s = re.sub(r'_+', '_', s)
    s = s.strip('_')
    if s and s[0].isdigit():
        s = '_' + s
    return s or 'unknown'


def _truncate(s: str, max_len: int) -> str:
    """Truncate string for display."""
    s = s.replace('\n', ' ')
    if len(s) > max_len:
        return s[:max_len-3] + '...'
    return s


def main():
    """CLI for generating tests."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate tests from history")
    parser.add_argument("--output", "-o", default="tests/test_approved_commands.py")
    parser.add_argument("--config", "-c", default="~/.config/claude-permissions-pro.toml")
    parser.add_argument("--max-sessions", type=int, help="Limit sessions to analyze")
    args = parser.parse_args()

    print("Extracting commands from Claude Code history...")
    commands = extract_all_commands(max_sessions=args.max_sessions)
    print(f"Found {len(commands)} unique commands")

    output_path = Path(args.output)
    count = generate_test_file(commands, output_path, config_path=args.config)
    print(f"Generated {count} test cases in {output_path}")


if __name__ == "__main__":
    main()
