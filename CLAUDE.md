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
cd /home/duane/primesignal/claude-permissions-pro
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Claude Code Integration

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
            "command": "/home/duane/primesignal/claude-permissions-pro/.venv/bin/python -m claude_permissions_pro.hook --config /home/duane/primesignal/claude-permissions-pro/config.toml",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
```

## CLI Commands

```bash
# Activate venv first
source .venv/bin/activate

# Analyze your Claude session history and show suggested patterns
claude-permissions-pro analyze --verbose

# Generate initial config from your history
claude-permissions-pro init -o config.toml

# Test a specific command against your config
claude-permissions-pro test -c config.toml "npm install && npm test"

# Generate pytest tests from your approved commands
claude-permissions-pro generate-tests -o tests/test_approved_commands.py -c config.toml
```

## Testing

```bash
source .venv/bin/activate
pip install pytest

# Run unit tests
pytest tests/test_shell_parser.py tests/test_matcher.py -v

# Generate and run tests from your history
claude-permissions-pro generate-tests -o tests/test_approved_commands.py -c config.toml
pytest tests/test_approved_commands.py -v

# Quick summary
pytest tests/ --tb=no -q
```

## How It Works

1. **Shell Parser** (`shell_parser.py`): Parses commands into segments, handling:
   - `&&` (AND chains)
   - `||` (OR chains)
   - `;` (sequential)
   - `|` (pipes)
   - Quoted strings (operators inside quotes aren't split)
   - Redirects like `2>&1` (not treated as background operator)

2. **Matcher** (`matcher.py`): Checks each segment against patterns:
   - Deny rules checked first
   - Allow rules checked second
   - In "smart" mode: ALL segments must match for chain to be allowed

3. **Hook** (`hook.py`): Integrates with Claude Code's PreToolUse hook system:
   - Reads JSON from stdin
   - Outputs allow/deny/passthrough decision to stdout

## Config Format

```toml
[settings]
mode = "smart"  # smart | paranoid | yolo

[[allow]]
pattern = "git *"

[[allow]]
pattern = "npm *"

[[deny]]
pattern = "rm -rf /*"

[[ask]]
pattern = "sudo *"
```

Patterns use glob syntax (`*` matches anything). Wrap in `/` for regex: `/^npm (install|test)/`
