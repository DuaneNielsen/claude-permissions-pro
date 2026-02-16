# Claude Permissions Pro

Smart permission hook for Claude Code that parses chained commands and evaluates each segment.

## File Structure

```
claude-permissions-pro/
├── src/
│   └── claude_permissions_pro/
│       ├── __init__.py          # Package init
│       ├── cli.py               # CLI commands (analyze, init, test, generate-tests, hook)
│       ├── generate_tests.py    # Generate pytest from session history
│       ├── history.py           # Extract commands from ~/.claude sessions
│       ├── hook.py              # Claude Code PreToolUse hook interface
│       ├── matcher.py           # Pattern matching with per-segment evaluation
│       └── shell_parser.py      # Parse &&, ||, ;, | chains respecting quotes
├── tests/
│   ├── conftest.py              # Pytest config
│   ├── test_shell_parser.py     # Tests for chain parsing
│   ├── test_matcher.py          # Tests for pattern matching
│   └── test_approved_commands.py # Auto-generated from your history (gitignored)
├── config.toml                  # Permission patterns (generated from history)
├── pyproject.toml               # Python package config
├── README.md                    # User readme
└── CLAUDE.md                    # This file
```

## Installation

```bash
cd claude-permissions-pro
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest  # For testing
```

## Learning From Your History (The Main Workflow)

The core idea: **use Claude Code to read your history, analyze your permissions, generate tests, and update your config**.

### Step 1: Analyze Your History

```bash
source .venv/bin/activate
claude-permissions-pro analyze --verbose
```

Reads `~/.claude/projects/*/` and outputs:
```
Total commands found: 4462
Unique base commands: 367
Chained commands (with &&, ||, etc.): 50

Top commands:
  git: 1137
  npm: 519
  curl: 436
  ...

Suggested patterns:
  [HIGH] git * (used 1137x)
  [HIGH] npm * (used 519x)
  [MED] curl * (used 436x)
```

### Step 2: Generate Config From History

```bash
claude-permissions-pro init -o config.toml
```

Creates `config.toml` with patterns based on your actual command usage.

### Step 3: Generate Tests From Your Approved Commands

```bash
claude-permissions-pro generate-tests -o tests/test_my_commands.py -c config.toml
```

This extracts every unique command from your history and creates a pytest test for each one. The test asserts that your config would ALLOW that command.

### Step 4: Run Tests to Find Coverage Gaps

```bash
pytest tests/test_my_commands.py --tb=no -q
```

Output:
```
486 failed, 862 passed in 3.06s
```

- **Passed** = commands your config would auto-approve
- **Failed** = commands you've used that aren't covered by your patterns

### Step 5: Identify Missing Patterns

```bash
# See which command types are failing
pytest tests/test_my_commands.py --tb=no -q 2>&1 | grep FAILED | \
  sed 's/.*TestApproved_//' | sed 's/::test_.*//' | \
  sort | uniq -c | sort -rn | head -20
```

Output:
```
     50 docker
     25 kubectl
     17 cargo
     ...
```

### Step 6: Update Config and Re-test

Add missing patterns to `config.toml`:
```toml
[[allow]]
pattern = "docker *"

[[allow]]
pattern = "kubectl *"

[[allow]]
pattern = "cargo *"
```

Re-run tests until you hit your target pass rate.

### Step 7: Deploy the Hook

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

Replace `/path/to/` with your actual install path.

## CLI Reference

```bash
# Analyze history (reads ~/.claude/projects/)
claude-permissions-pro analyze [--verbose] [--max-sessions N] [--output FILE]

# Generate config from history
claude-permissions-pro init [--output FILE]

# Test a single command against config
claude-permissions-pro test --config FILE "command to test"

# Generate pytest tests from history
claude-permissions-pro generate-tests --config FILE [--output FILE]

# Run as Claude Code hook (reads JSON from stdin)
claude-permissions-pro hook --config FILE
```

## Testing

```bash
source .venv/bin/activate

# Unit tests (fast, no history needed)
pytest tests/test_shell_parser.py tests/test_matcher.py -v

# Generate tests from YOUR history
claude-permissions-pro generate-tests -o tests/test_my_commands.py -c config.toml

# Run generated tests
pytest tests/test_my_commands.py -v

# Quick summary
pytest tests/test_my_commands.py --tb=no -q

# See failing command types
pytest tests/test_my_commands.py --tb=no -q 2>&1 | grep FAILED | \
  sed 's/.*TestApproved_//' | sed 's/::test_.*//' | \
  sort | uniq -c | sort -rn
```

## How It Works

1. **Shell Parser** (`shell_parser.py`): Parses commands into segments
   - Splits on `&&`, `||`, `;`, `|`
   - Respects quoted strings (won't split `echo "a && b"`)
   - Handles redirects (`2>&1` stays intact)

2. **Matcher** (`matcher.py`): Checks each segment against patterns
   - Deny rules checked first
   - Allow rules checked second
   - In "smart" mode: ALL segments must match for chain to be allowed

3. **History** (`history.py`): Extracts commands from `~/.claude/projects/`
   - Reads JSONL session files
   - Extracts Bash tool invocations
   - Counts frequency for pattern suggestions

4. **Hook** (`hook.py`): Claude Code integration
   - Reads JSON from stdin (Claude Code protocol)
   - Outputs allow/deny/passthrough to stdout

## Config Format

```toml
[settings]
mode = "smart"  # smart | paranoid | yolo

# Allow patterns (auto-approve if matched)
[[allow]]
pattern = "git *"

[[allow]]
pattern = "npm *"

# Deny patterns (block, checked first)
[[deny]]
pattern = "rm -rf /*"

# Ask patterns (always prompt user)
[[ask]]
pattern = "sudo *"
```

**Pattern syntax:**
- Glob: `npm *`, `git commit *`
- Regex: `/^npm (install|test|run)/`

**Modes:**
- `smart`: Allow chain only if ALL segments match
- `paranoid`: Ask if ANY segment is unknown
- `yolo`: Allow if ANY segment matches
