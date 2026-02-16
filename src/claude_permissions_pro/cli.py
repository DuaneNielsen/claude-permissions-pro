#!/usr/bin/env python3
"""
CLI for Claude Permissions Pro.

Commands:
    analyze   - Analyze session history and suggest patterns
    hook      - Run as Claude Code hook
    test      - Test a command against your config
    init      - Generate initial config from history
"""

import argparse
import sys
from pathlib import Path

from . import __version__


def cmd_analyze(args):
    """Analyze session history and show suggestions."""
    from .history import analyze_history, export_suggested_config

    print(f"Analyzing Claude Code session history...")
    print()

    analysis = analyze_history(
        max_sessions=args.max_sessions,
        min_frequency=args.min_frequency
    )

    print(f"Total commands found: {analysis.total_commands}")
    print(f"Unique base commands: {len(analysis.unique_base_commands)}")
    print(f"Chained commands (with &&, ||, etc.): {len(analysis.chained_commands)}")
    print()

    print("Top commands:")
    for cmd, count in analysis.unique_base_commands.most_common(20):
        print(f"  {cmd}: {count}")
    print()

    print("Suggested patterns:")
    for suggestion in analysis.suggested_patterns[:15]:
        conf = "HIGH" if suggestion.confidence > 0.7 else "MED" if suggestion.confidence > 0.4 else "LOW"
        print(f"  [{conf}] {suggestion.pattern} (used {suggestion.frequency}x)")
        if args.verbose and suggestion.example_commands:
            for ex in suggestion.example_commands[:2]:
                print(f"        e.g. {ex[:60]}...")
    print()

    if analysis.chained_commands:
        print("Sample chained commands (these will be parsed intelligently):")
        for cmd in analysis.chained_commands[:5]:
            print(f"  {cmd[:80]}...")
    print()

    if args.output:
        config = export_suggested_config(analysis, min_confidence=0.5)
        output_path = Path(args.output)
        output_path.write_text(config)
        print(f"Config written to: {output_path}")
    else:
        print("Use --output FILE.toml to save suggested config")


def cmd_hook(args):
    """Run as Claude Code hook."""
    from .hook import run_hook

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    run_hook(config_path)


def cmd_test(args):
    """Test a command against config."""
    from .hook import Config
    from .matcher import Matcher
    from .shell_parser import parse_command

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = Config.load(config_path)
    matcher = Matcher(
        allow_patterns=config.allow_patterns,
        deny_patterns=config.deny_patterns,
        mode=config.mode,
    )

    command = args.command
    parsed = parse_command(command)

    print(f"Command: {command}")
    print(f"Is simple: {parsed.is_simple}")
    print(f"Segments: {len(parsed.segments)}")
    for i, seg in enumerate(parsed.segments):
        op = seg.operator_before.value if seg.operator_before else "START"
        print(f"  [{op}] {seg.command}")
    print()

    result = matcher.check(command)
    print(f"Decision: {result.decision.value.upper()}")
    print(f"Reason: {result.reason}")
    if result.matched_rule:
        print(f"Matched rule: {result.matched_rule}")


def cmd_init(args):
    """Generate initial config from history."""
    from .history import analyze_history, export_suggested_config

    print("Analyzing your Claude Code history to generate config...")
    analysis = analyze_history(min_frequency=2)

    config = export_suggested_config(analysis, min_confidence=0.5)

    output_path = Path(args.output) if args.output else Path.home() / ".config" / "claude-permissions-pro.toml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(config)

    print(f"Config written to: {output_path}")
    print()
    print("To use with Claude Code, add to your .claude/settings.json:")
    print()
    print('''{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": "claude-permissions-pro hook --config ''' + str(output_path) + '''"
      }]
    }]
  }
}''')


def cmd_generate_tests(args):
    """Generate pytest tests from approved commands in history."""
    from .generate_tests import extract_all_commands, generate_test_file

    print("Extracting commands from Claude Code history...")
    commands = extract_all_commands(max_sessions=args.max_sessions)
    print(f"Found {len(commands)} unique commands")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = generate_test_file(commands, output_path, config_path=args.config)
    print(f"Generated {count} test cases in {output_path}")
    print()
    print("Run tests with:")
    print(f"  pytest {output_path} -v")


def main():
    parser = argparse.ArgumentParser(
        description="Claude Permissions Pro - Smart permission hook for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # analyze command
    p_analyze = subparsers.add_parser("analyze", help="Analyze session history")
    p_analyze.add_argument("--max-sessions", type=int, help="Max sessions to analyze")
    p_analyze.add_argument("--min-frequency", type=int, default=2, help="Min command frequency")
    p_analyze.add_argument("--output", "-o", help="Output config file path")
    p_analyze.add_argument("--verbose", "-v", action="store_true", help="Show examples")
    p_analyze.set_defaults(func=cmd_analyze)

    # hook command
    p_hook = subparsers.add_parser("hook", help="Run as Claude Code hook")
    p_hook.add_argument("--config", "-c", required=True, help="Config file path")
    p_hook.set_defaults(func=cmd_hook)

    # test command
    p_test = subparsers.add_parser("test", help="Test a command against config")
    p_test.add_argument("--config", "-c", required=True, help="Config file path")
    p_test.add_argument("command", help="Command to test")
    p_test.set_defaults(func=cmd_test)

    # init command
    p_init = subparsers.add_parser("init", help="Generate config from history")
    p_init.add_argument("--output", "-o", help="Output config file path")
    p_init.set_defaults(func=cmd_init)

    # generate-tests command
    p_gentests = subparsers.add_parser("generate-tests", help="Generate pytest tests from history")
    p_gentests.add_argument("--output", "-o", default="tests/test_approved_commands.py",
                            help="Output test file path")
    p_gentests.add_argument("--config", "-c", default="~/.config/claude-permissions-pro.toml",
                            help="Config file path for tests to use")
    p_gentests.add_argument("--max-sessions", type=int, help="Limit sessions to analyze")
    p_gentests.set_defaults(func=cmd_generate_tests)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
