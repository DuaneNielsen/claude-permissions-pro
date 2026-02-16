# Claude Permissions Pro

A pro-productivity permission hook for Claude Code that actually understands chained commands.

## Features

- **Smart Chain Parsing**: Parses `&&`, `||`, `;`, `|` and evaluates EACH segment
- **Per-Segment Matching**: `npm install && npm test` allowed if BOTH match patterns
- **History Analysis**: Extracts commands from your Claude session logs
- **Pattern Suggestion**: Analyzes your history and suggests allow rules
- **Test Generation**: Creates pytest tests from your approved commands

## Philosophy

Other hooks block anything with `&&` or `|`. With LLMs nearly always chaining commands, these hooks are pointless.

We parse the chain, check each part, and allow it if everything is safe.

## Quick Start

```bash
git clone <repo>
cd claude-permissions-pro
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Analyze your history and generate config
claude-permissions-pro init -o config.toml

# Test it
claude-permissions-pro test -c config.toml "git status && npm test"
```

## Learning From Your History

The killer feature: analyze your actual Claude Code usage to build permission patterns.

### Step 1: Analyze Your History

```bash
claude-permissions-pro analyze --verbose
```

This reads all sessions from `~/.claude/projects/` and shows:
- Total commands found
- Most frequent commands
- Suggested patterns with confidence scores
- Chained commands that will now auto-approve

### Step 2: Generate Config

```bash
claude-permissions-pro init -o config.toml
```

Creates a `config.toml` with patterns based on your actual usage.

### Step 3: Generate Tests

```bash
claude-permissions-pro generate-tests -o tests/test_my_commands.py -c config.toml
```

This creates pytest tests from every command in your history. Each test verifies that your config would allow commands you've previously approved.

### Step 4: Run Tests to Find Gaps

```bash
pip install pytest
pytest tests/test_my_commands.py --tb=no -q
```

Output shows pass/fail rate:
```
486 failed, 862 passed in 3.06s
```

Failed tests = commands you've used that your config doesn't cover yet.

### Step 5: Iterate

Check what's failing:
```bash
pytest tests/test_my_commands.py --tb=no -q 2>&1 | grep FAILED | \
  sed 's/.*TestApproved_//' | sed 's/::test_.*//' | \
  sort | uniq -c | sort -rn | head -20
```

Add missing patterns to `config.toml`, re-run tests until you hit your target pass rate.

### Step 6: Deploy

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/claude-permissions-pro/.venv/bin/python -m claude_permissions_pro.hook --config /path/to/config.toml",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
```

## Configuration

```toml
[settings]
mode = "smart"  # smart | paranoid | yolo

# Allow patterns - checked after deny
[[allow]]
pattern = "npm *"

[[allow]]
pattern = "git *"

# Deny patterns - checked first
[[deny]]
pattern = "rm -rf /*"

# Ask patterns - always prompt (for dangerous but sometimes needed commands)
[[ask]]
pattern = "sudo *"
```

**Modes:**
- `smart` (default): Allow chain if ALL segments match allow patterns
- `paranoid`: Ask if ANY segment is unknown
- `yolo`: Allow chain if ANY segment matches

**Pattern syntax:**
- Glob: `npm *`, `git commit *`
- Regex: `/^npm (install|test|run)/`

## CLI Reference

```bash
claude-permissions-pro analyze [--verbose] [--max-sessions N] [--output FILE]
claude-permissions-pro init [--output FILE]
claude-permissions-pro test --config FILE "command to test"
claude-permissions-pro generate-tests --config FILE [--output FILE]
claude-permissions-pro hook --config FILE  # Used by Claude Code
```

## How It Works

1. **Shell Parser**: Splits `npm install && npm test` into `['npm install', 'npm test']`
2. **Path Normalization**: `.venv/bin/python` → `python` for matching
3. **Redirect Handling**: `2>&1` kept intact (not split as background operator)
4. **Per-Segment Matching**: Each segment checked against patterns
5. **Decision**: Allow only if all segments pass (in smart mode)
