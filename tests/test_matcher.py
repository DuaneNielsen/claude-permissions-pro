"""Tests for pattern matching."""

import pytest
from claude_permissions_pro.matcher import (
    Matcher,
    Decision,
    Pattern,
)


class TestPattern:
    """Tests for Pattern class."""

    def test_glob_pattern_simple(self):
        p = Pattern.from_string("npm *")
        assert p.matches("npm install")
        assert p.matches("npm test")
        assert not p.matches("yarn install")

    def test_glob_pattern_exact(self):
        p = Pattern.from_string("npm install")
        assert p.matches("npm install")
        assert not p.matches("npm test")

    def test_regex_pattern(self):
        p = Pattern.from_string("/^npm (install|test|run)/")
        assert p.matches("npm install foo")
        assert p.matches("npm test")
        assert p.matches("npm run build")
        assert not p.matches("npm publish")

    def test_glob_with_subcommand(self):
        p = Pattern.from_string("git commit *")
        assert p.matches("git commit -m 'message'")
        assert not p.matches("git push")


class TestMatcher:
    """Tests for Matcher class."""

    def test_simple_allow(self):
        matcher = Matcher(allow_patterns=["npm *"])
        result = matcher.check("npm install")
        assert result.decision == Decision.ALLOW

    def test_simple_deny(self):
        matcher = Matcher(
            allow_patterns=["npm *"],
            deny_patterns=["rm -rf *"]
        )
        result = matcher.check("rm -rf /")
        assert result.decision == Decision.DENY

    def test_deny_takes_precedence(self):
        """Deny patterns are checked before allow patterns."""
        matcher = Matcher(
            allow_patterns=["*"],  # Allow everything
            deny_patterns=["rm *"]
        )
        result = matcher.check("rm file.txt")
        assert result.decision == Decision.DENY

    def test_passthrough_unknown(self):
        matcher = Matcher(allow_patterns=["npm *"])
        result = matcher.check("unknown-command")
        assert result.decision == Decision.ASK

    def test_chain_all_allowed_smart_mode(self):
        """In smart mode, allow chain if ALL segments match."""
        matcher = Matcher(
            allow_patterns=["npm *", "git *"],
            mode="smart"
        )
        result = matcher.check("npm install && npm test")
        assert result.decision == Decision.ALLOW
        assert result.segments_checked is not None
        assert len(result.segments_checked) == 2

    def test_chain_partial_match_smart_mode(self):
        """In smart mode, ask if some segments don't match."""
        matcher = Matcher(
            allow_patterns=["npm *"],
            mode="smart"
        )
        result = matcher.check("npm install && unknown-cmd")
        assert result.decision == Decision.ASK

    def test_chain_with_deny_segment(self):
        """Deny the whole chain if any segment is denied."""
        matcher = Matcher(
            allow_patterns=["npm *"],
            deny_patterns=["rm *"]
        )
        result = matcher.check("npm install && rm -rf /")
        assert result.decision == Decision.DENY

    def test_chain_yolo_mode(self):
        """In yolo mode, allow if ANY segment matches."""
        matcher = Matcher(
            allow_patterns=["npm *"],
            mode="yolo"
        )
        result = matcher.check("npm install && unknown-cmd")
        assert result.decision == Decision.ALLOW

    def test_pipe_command(self):
        """Piped commands are also parsed."""
        matcher = Matcher(
            allow_patterns=["cat *", "grep *"],
            mode="smart"
        )
        result = matcher.check("cat file.txt | grep error")
        assert result.decision == Decision.ALLOW

    def test_pipe_partial_match(self):
        """Pipe with unknown command."""
        matcher = Matcher(
            allow_patterns=["cat *"],
            mode="smart"
        )
        result = matcher.check("cat file.txt | unknown-filter")
        assert result.decision == Decision.ASK

    def test_complex_chain(self):
        """Real-world complex chain."""
        matcher = Matcher(
            allow_patterns=["git *", "npm *"],
            mode="smart"
        )
        result = matcher.check("git add . && git commit -m 'update' && npm version patch")
        assert result.decision == Decision.ALLOW

    def test_quoted_operators_not_split(self):
        """Operators inside quotes don't split command."""
        matcher = Matcher(allow_patterns=["echo *"])
        result = matcher.check("echo 'hello && world'")
        assert result.decision == Decision.ALLOW
        # Should be treated as single command

    def test_multiple_patterns(self):
        """Multiple patterns for same command."""
        matcher = Matcher(
            allow_patterns=["npm install *", "npm test", "npm run *"]
        )
        assert matcher.check("npm install foo").decision == Decision.ALLOW
        assert matcher.check("npm test").decision == Decision.ALLOW
        assert matcher.check("npm run build").decision == Decision.ALLOW
        assert matcher.check("npm publish").decision == Decision.ASK
