"""
LLM judge for automated safety evaluation of shell commands.

Routes ASK decisions to an LLM (OpenAI-compatible API) for evaluation,
reducing manual permission prompts while maintaining security.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, field


@dataclass
class JudgeConfig:
    """Configuration for the LLM judge."""
    enabled: bool = False
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "https://api.openai.com/v1"
    timeout: int = 5


@dataclass
class JudgeResult:
    """Result from the LLM judge evaluation."""
    decision: str  # "ALLOW" or "DENY"
    reason: str


class JudgeError(Exception):
    """Raised when judge evaluation fails."""
    pass


SYSTEM_PROMPT = """You are a security evaluator for shell commands executed by an AI coding assistant.

Your job is to decide whether a shell command is SAFE to auto-approve or whether it needs human review.

ALLOW commands that are:
- Read-only operations (listing files, reading content, checking status)
- Standard development operations (building, testing, linting, formatting)
- Package management (install, update) in project directories
- Git operations that don't rewrite history or force-push
- Creating/editing files in project directories

DENY commands that are:
- Destructive operations on system/home directories
- Network operations that exfiltrate data
- Commands that modify system configuration
- Commands with obfuscated or encoded payloads
- Privilege escalation attempts
- Commands that could affect other users or services

When in doubt, DENY. It's better to ask the human than to auto-approve something risky.

Respond with exactly two lines:
Line 1: ALLOW or DENY
Line 2: Brief reason (one sentence)"""


def _build_user_prompt(command: str, segments: list[str], cwd: str) -> str:
    """Build the user prompt for the judge."""
    parts = [f"Command: {command}"]
    if len(segments) > 1:
        parts.append(f"Segments: {segments}")
    parts.append(f"Working directory: {cwd}")
    return "\n".join(parts)


def _parse_response(text: str) -> JudgeResult:
    """Parse the judge LLM response into a JudgeResult."""
    lines = text.strip().splitlines()
    if not lines:
        raise JudgeError("Empty response from judge")

    decision = lines[0].strip().upper()
    if decision not in ("ALLOW", "DENY"):
        raise JudgeError(f"Invalid decision from judge: {lines[0].strip()!r}")

    reason = lines[1].strip() if len(lines) > 1 else "No reason provided"
    return JudgeResult(decision=decision, reason=reason)


def evaluate(command: str, segments: list[str], config: JudgeConfig, cwd: str = "") -> JudgeResult:
    """
    Evaluate a command using the LLM judge.

    Args:
        command: The full command string
        segments: Individual command segments (from shell parser)
        config: Judge configuration
        cwd: Current working directory

    Returns:
        JudgeResult with decision and reason

    Raises:
        JudgeError: On API errors, timeouts, or malformed responses
    """
    api_key = os.environ.get(config.api_key_env, "")
    if not api_key:
        raise JudgeError(f"API key not found in ${config.api_key_env}")

    url = f"{config.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": config.model,
        "temperature": 0,
        "max_tokens": 100,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(command, segments, cwd)},
        ],
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise JudgeError(f"API request failed: {e}") from e
    except json.JSONDecodeError as e:
        raise JudgeError(f"Invalid JSON response: {e}") from e

    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise JudgeError(f"Unexpected response structure: {e}") from e

    return _parse_response(text)
