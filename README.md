# Claude Permissions Pro

A pro-productivity permission hook for Claude Code that actually understands chained commands.

## Features

- **Smart Chain Parsing**: Parses `&&`, `||`, `;`, `|` and evaluates EACH segment
- **Per-Segment Matching**: `npm install && npm test` allowed if BOTH match patterns
- **History Analysis**: Extracts commands from your Claude session logs
- **Pattern Suggestion**: Analyzes your history and suggests allow rules
- **Learning Mode**: Auto-generates patterns from approved commands

## Philosophy

Other hooks block anything with `&&` or `|`. That's for losers.

We parse the chain, check each part, and allow it if everything is safe.

## Installation

```bash
# Install dependencies
pip install -e .

# Generate config from your history
claude-permissions-pro analyze

# Run as hook
claude-permissions-pro hook --config ~/.config/claude-permissions-pro.toml
```

## Configuration

```toml
[settings]
mode = "smart"  # smart | paranoid | yolo

# Commands are parsed and each segment checked
[[allow]]
pattern = "npm *"

[[allow]]
pattern = "git *"

[[allow]]
pattern = "cargo *"

# These work for chains too!
# "npm install && npm test" -> both segments match "npm *" -> ALLOWED
```
