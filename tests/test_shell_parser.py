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
        assert len(result.segments) == 1  # && is inside $(), not split
        assert result.segments[0].has_subshell

    def test_backtick_substitution(self):
        """Backticks should not be split on internal operators."""
        result = parse_command("echo `cat file | wc -l`")
        assert len(result.segments) == 1  # | is inside backticks, not split

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

    def test_ampersand_redirect_not_split(self):
        """&> and &>> redirects should not split on the &."""
        result = parse_command("xdg-open /tmp/foo.jpg &>/dev/null")
        assert result.is_simple
        assert len(result.segments) == 1
        assert result.segments[0].command == "xdg-open /tmp/foo.jpg &>/dev/null"

    def test_ampersand_redirect_in_chain(self):
        """&>/dev/null inside a && chain should not cause extra splits."""
        result = parse_command(
            'curl -s http://example.com 2>&1 && xdg-open /tmp/out.jpg &>/dev/null'
        )
        assert len(result.segments) == 2
        assert result.segments[0].command == "curl -s http://example.com 2>&1"
        assert result.segments[1].operator_before == Operator.AND
        assert result.segments[1].command == "xdg-open /tmp/out.jpg &>/dev/null"

    def test_ampersand_redirect_then_background(self):
        """&>/dev/null followed by trailing & (background) should split correctly."""
        result = parse_command(
            'xdg-open /tmp/out.jpg &>/dev/null &'
        )
        # trailing & with empty segment after it = 1 segment (empty trailing dropped)
        assert len(result.segments) == 1
        assert result.segments[0].command == "xdg-open /tmp/out.jpg &>/dev/null"

    def test_ampersand_redirect_append(self):
        """&>> (append) should not split either."""
        result = parse_command("mycommand &>>/tmp/log.txt")
        assert result.is_simple
        assert len(result.segments) == 1

    def test_semicolon_after_subshell(self):
        """Semicolons after $() should split correctly."""
        result = parse_command('x=$(echo hi); echo done')
        assert len(result.segments) == 2
        assert result.segments[0].command == "x=$(echo hi)"
        assert result.segments[1].command == "echo done"

    def test_and_after_subshell(self):
        """&& after $() should split correctly."""
        result = parse_command('x=$(echo hi) && echo done')
        assert len(result.segments) == 2
        assert result.segments[0].command == "x=$(echo hi)"
        assert result.segments[1].command == "echo done"

    def test_nested_subshell(self):
        """Nested $() should track depth correctly."""
        result = parse_command('x=$(echo $(date)); echo done')
        assert len(result.segments) == 2
        assert result.segments[0].command == "x=$(echo $(date))"
        assert result.segments[1].command == "echo done"

    def test_for_loop_with_subshell(self):
        """For loop with $() assignment and semicolons should parse all segments."""
        cmd = (
            'for tid in abc def; do '
            'count=$(curl -s "http://example.com/$tid" | python3 -c "import sys,json;'
            ' print(len(json.load(sys.stdin)))" 2>/dev/null); '
            'echo "$tid: $count"; '
            'done'
        )
        result = parse_command(cmd)
        commands = [s.command for s in result.segments]
        assert 'for tid in abc def' in commands
        assert 'done' in commands
        # The body should be split into separate segments by ;
        assert len(result.segments) >= 4

    def test_newline_as_separator(self):
        """Newlines outside quotes should act as command separators."""
        result = parse_command('echo hello\necho world')
        assert len(result.segments) == 2
        assert result.segments[0].command == "echo hello"
        assert result.segments[1].command == "echo world"

    def test_newline_inside_quotes_not_separator(self):
        """Newlines inside quotes should not split."""
        result = parse_command('echo "hello\nworld"')
        assert len(result.segments) == 1

    def test_heredoc_not_split(self):
        """Heredoc body should not be split on newlines."""
        cmd = "python3 << 'EOF'\nimport json\nprint('hello')\nEOF"
        result = parse_command(cmd)
        assert len(result.segments) == 1
        assert "import json" in result.segments[0].command

    def test_heredoc_then_more_commands(self):
        """Commands after heredoc should be separate segments."""
        cmd = "cat << EOF\nhello\nworld\nEOF\necho done"
        result = parse_command(cmd)
        assert len(result.segments) == 2
        assert "hello" in result.segments[0].command
        assert result.segments[1].command == "echo done"

    def test_heredoc_with_chain_before(self):
        """&& before heredoc should split, but heredoc body stays together."""
        cmd = "source .venv/bin/activate && python3 << 'EOF'\nimport sys\nprint(sys.version)\nEOF"
        result = parse_command(cmd)
        assert len(result.segments) == 2
        assert result.segments[0].command == "source .venv/bin/activate"
        assert "import sys" in result.segments[1].command

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
