"""Tests for shell command parser."""

import pytest
from claude_permissions_pro.shell_parser import (
    parse_command,
    extract_base_command,
    Operator,
)


class TestParseCommand:
    """Tests for parse_command function."""

    def test_simple_command(self):
        """Simple command with no operators."""
        result = parse_command("npm install")
        assert result.is_simple
        assert len(result.segments) == 1
        assert result.segments[0].command == "npm install"

    def test_and_chain(self):
        """Commands chained with &&."""
        result = parse_command("npm install && npm test")
        assert not result.is_simple
        assert len(result.segments) == 2
        assert result.segments[0].command == "npm install"
        assert result.segments[0].operator_before is None
        assert result.segments[1].command == "npm test"
        assert result.segments[1].operator_before == Operator.AND

    def test_or_chain(self):
        """Commands chained with ||."""
        result = parse_command("npm test || echo 'failed'")
        assert len(result.segments) == 2
        assert result.segments[1].operator_before == Operator.OR

    def test_semicolon_chain(self):
        """Commands separated by semicolon."""
        result = parse_command("cd /tmp; ls -la")
        assert len(result.segments) == 2
        assert result.segments[1].operator_before == Operator.SEMI

    def test_pipe(self):
        """Commands connected with pipe."""
        result = parse_command("cat file.txt | grep error")
        assert len(result.segments) == 2
        assert result.segments[0].command == "cat file.txt"
        assert result.segments[1].command == "grep error"
        assert result.segments[1].operator_before == Operator.PIPE

    def test_multiple_operators(self):
        """Multiple different operators."""
        result = parse_command("npm install && npm build && npm test")
        assert len(result.segments) == 3
        assert result.segments[0].command == "npm install"
        assert result.segments[1].command == "npm build"
        assert result.segments[2].command == "npm test"

    def test_quoted_string_with_operator(self):
        """Operator inside quotes should not split."""
        result = parse_command("echo 'hello && world'")
        assert result.is_simple
        assert len(result.segments) == 1
        assert "&&" in result.segments[0].command

    def test_double_quoted_string(self):
        """Operator inside double quotes should not split."""
        result = parse_command('echo "test | value"')
        assert result.is_simple
        assert len(result.segments) == 1

    def test_subshell_command_substitution(self):
        """$() should not be split on internal operators."""
        result = parse_command("echo $(cat file && wc -l)")
        assert result.is_simple  # The && is inside $()
        assert len(result.segments) == 1
        assert result.segments[0].has_subshell

    def test_backtick_substitution(self):
        """Backticks should not be split on internal operators."""
        result = parse_command("echo `cat file | wc -l`")
        assert result.is_simple
        assert len(result.segments) == 1

    def test_background_operator(self):
        """Single & for background."""
        result = parse_command("sleep 10 & echo 'started'")
        assert len(result.segments) == 2
        assert result.segments[1].operator_before == Operator.BG

    def test_escaped_characters(self):
        """Escaped operators should not split."""
        result = parse_command(r"echo hello \&\& world")
        assert len(result.segments) == 1

    def test_redirect_detection(self):
        """Detect redirects in command."""
        result = parse_command("npm test > output.log 2>&1")
        assert result.segments[0].has_redirect

    def test_complex_chain(self):
        """Complex real-world chain."""
        result = parse_command("git add . && git commit -m 'update' && git push")
        assert len(result.segments) == 3
        for seg in result.segments:
            assert seg.command.startswith("git")


class TestExtractBaseCommand:
    """Tests for extract_base_command function."""

    def test_simple_command(self):
        assert extract_base_command("npm install") == "npm"

    def test_with_path(self):
        assert extract_base_command("/usr/bin/python3 script.py") == "python3"

    def test_with_env_var(self):
        assert extract_base_command("NODE_ENV=production npm start") == "npm"

    def test_multiple_env_vars(self):
        assert extract_base_command("FOO=bar BAZ=qux npm test") == "npm"

    def test_quoted_args(self):
        assert extract_base_command('git commit -m "message"') == "git"
