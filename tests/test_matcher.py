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


class TestEnvVarStripping:
    """Tests for env-var prefix stripping in Pattern."""

    def test_simple_env_prefix(self):
        p = Pattern.from_string("docker *")
        assert p.matches("ARCH=amd64 docker build .")

    def test_multiple_env_prefixes(self):
        p = Pattern.from_string("docker *")
        assert p.matches("ARCH=amd64 TAG=latest docker build .")

    def test_quoted_env_value_with_spaces(self):
        p = Pattern.from_string("docker *")
        assert p.matches('COMPUTE_LEVEL="50 60 70 80 90" docker build .')

    def test_single_quoted_env_value_with_spaces(self):
        p = Pattern.from_string("make *")
        assert p.matches("CFLAGS='-O2 -Wall' make all")

    def test_bare_assignment_no_strip(self):
        """Bare assignment with no command after should not match."""
        p = Pattern.from_string("docker *")
        assert not p.matches("FOO=bar")


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

    def test_xdg_open_with_ampersand_redirect(self):
        """xdg-open with &>/dev/null should be allowed when pattern exists."""
        matcher = Matcher(
            allow_patterns=["curl *", "xdg-open *"],
            mode="smart"
        )
        result = matcher.check(
            'curl -sk -b /tmp/cookies -o /tmp/cam.jpg '
            '"https://localhost:8971/api/cam/latest.jpg?bbox=1&h=480" 2>&1 '
            '&& xdg-open /tmp/cam.jpg &>/dev/null &'
        )
        assert result.decision == Decision.ALLOW

    def test_for_loop_with_subshell_all_allowed(self):
        """Multi-line for loop with known commands should be allowed."""
        matcher = Matcher(
            allow_patterns=[
                "for *", "do", "do *", "done", "curl *",
                "python3 *", "echo *",
            ],
            mode="smart"
        )
        cmd = (
            'for tid in abc def; do '
            'count=$(curl -s "http://example.com/$tid" | python3 -c "import sys,json;'
            ' print(len(json.load(sys.stdin)))" 2>/dev/null); '
            'echo "$tid: $count"; '
            'done'
        )
        result = matcher.check(cmd)
        assert result.decision == Decision.ALLOW

    def test_variable_assignment_with_subshell(self):
        """Variable assignments with $() should be auto-allowed."""
        matcher = Matcher(allow_patterns=["echo *"], mode="smart")
        result = matcher.check('count=$(echo 42); echo $count')
        assert result.decision == Decision.ALLOW

    def test_env_prefix_with_quoted_spaces(self):
        """Env vars with quoted values containing spaces should be stripped."""
        matcher = Matcher(
            allow_patterns=["docker *"],
            mode="smart"
        )
        result = matcher.check(
            'ARCH=amd64 COMPUTE_LEVEL="50 60 70 80 90" docker buildx bake '
            '--file=docker/tensorrt/trt.hcl tensorrt --load'
        )
        assert result.decision == Decision.ALLOW

    def test_frigate_build_chain(self):
        """Full frigate build chain: cd && make && docker buildx | tail."""
        matcher = Matcher(
            allow_patterns=["cd *", "make *", "docker *", "tail *"],
            mode="smart"
        )
        result = matcher.check(
            'cd /home/duane/frigate-source && make version 2>&1 '
            '&& ARCH=amd64 COMPUTE_LEVEL="50 60 70 80 90" docker buildx bake '
            '--file=docker/tensorrt/trt.hcl tensorrt '
            '--set tensorrt.tags=frigate:latest-tensorrt --load 2>&1 | tail -5'
        )
        assert result.decision == Decision.ALLOW
        assert len(result.segments_checked) == 4

    def test_docker_compose_up(self):
        """docker compose up -d should be allowed."""
        matcher = Matcher(allow_patterns=["docker *"])
        assert matcher.check("docker compose up -d").decision == Decision.ALLOW
        assert matcher.check("docker compose up -d frigate").decision == Decision.ALLOW

    def test_docker_exec(self):
        """docker exec should be allowed."""
        matcher = Matcher(allow_patterns=["docker *"])
        result = matcher.check("docker exec frigate cat /config/config.yml")
        assert result.decision == Decision.ALLOW

    def test_docker_logs(self):
        """docker logs should be allowed."""
        matcher = Matcher(allow_patterns=["docker *"])
        result = matcher.check("docker logs frigate --tail 50")
        assert result.decision == Decision.ALLOW

    def test_multiple_patterns(self):
        """Multiple patterns for same command."""
        matcher = Matcher(
            allow_patterns=["npm install *", "npm test", "npm run *"]
        )
        assert matcher.check("npm install foo").decision == Decision.ALLOW
        assert matcher.check("npm test").decision == Decision.ALLOW
        assert matcher.check("npm run build").decision == Decision.ALLOW
        assert matcher.check("npm publish").decision == Decision.ASK
