"""Tests for the decision logger."""

import json

import pytest

from claude_permissions_pro.logger import (
    DecisionRecord,
    log_decision,
    iter_decisions,
)


class TestDecisionRecord:
    def test_roundtrip_json(self):
        record = DecisionRecord(
            timestamp="2026-03-18T12:00:00+00:00",
            command="git status",
            cwd="/home/user/project",
            matcher_decision="allow",
            matched_rule="git *",
            judge_decision=None,
            judge_reason=None,
            final_decision="allow",
            segments=["git status"],
        )
        json_str = record.to_json()
        restored = DecisionRecord.from_json(json_str)
        assert restored == record

    def test_roundtrip_with_judge(self):
        record = DecisionRecord(
            timestamp="2026-03-18T12:00:00+00:00",
            command="some-unknown-cmd",
            cwd="/tmp",
            matcher_decision="ask",
            matched_rule=None,
            judge_decision="DENY",
            judge_reason="Potentially dangerous",
            final_decision="passthrough",
            segments=["some-unknown-cmd"],
        )
        json_str = record.to_json()
        restored = DecisionRecord.from_json(json_str)
        assert restored == record


class TestLogDecision:
    def test_writes_jsonl(self, tmp_path):
        log_file = tmp_path / "test.jsonl"

        log_decision(
            command="git status",
            cwd="/home/user",
            matcher_decision="allow",
            matched_rule="git *",
            final_decision="allow",
            log_file=log_file,
        )
        log_decision(
            command="rm -rf /",
            cwd="/home/user",
            matcher_decision="deny",
            matched_rule="rm -rf *",
            final_decision="deny",
            log_file=log_file,
        )

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

        first = json.loads(lines[0])
        assert first["command"] == "git status"
        assert first["final_decision"] == "allow"

        second = json.loads(lines[1])
        assert second["command"] == "rm -rf /"
        assert second["final_decision"] == "deny"

    def test_creates_parent_dirs(self, tmp_path):
        log_file = tmp_path / "nested" / "dir" / "test.jsonl"
        log_decision(
            command="ls",
            cwd="/tmp",
            matcher_decision="ask",
            final_decision="passthrough",
            log_file=log_file,
        )
        assert log_file.exists()


class TestIterDecisions:
    def test_reads_logged_decisions(self, tmp_path):
        log_file = tmp_path / "test.jsonl"

        for cmd in ["git status", "npm test", "unknown-cmd"]:
            log_decision(
                command=cmd,
                cwd="/tmp",
                matcher_decision="allow" if cmd != "unknown-cmd" else "ask",
                final_decision="allow" if cmd != "unknown-cmd" else "passthrough",
                log_file=log_file,
            )

        records = list(iter_decisions(log_file))
        assert len(records) == 3
        assert records[0].command == "git status"
        assert records[2].final_decision == "passthrough"

    def test_missing_file_yields_nothing(self, tmp_path):
        log_file = tmp_path / "nonexistent.jsonl"
        records = list(iter_decisions(log_file))
        assert records == []
