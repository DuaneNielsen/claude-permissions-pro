#!/usr/bin/env python3
"""
PreToolUse hook entry point for the plugin.

Bootstraps the module path from CLAUDE_PLUGIN_ROOT and runs the hook.
Config resolution order:
  1. ~/.config/claude-permissions-pro/config.toml  (user customized)
  2. $CLAUDE_PLUGIN_ROOT/config.toml               (bundled default)
"""

import os
import sys
from pathlib import Path

# Bootstrap: add the plugin's src/ to the module path
plugin_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(plugin_root / "src"))

from claude_permissions_pro.hook import run_hook  # noqa: E402

# Config resolution
user_config = Path.home() / ".config" / "claude-permissions-pro" / "config.toml"
bundled_config = plugin_root / "config.toml"

if user_config.exists():
    config_path = user_config
elif bundled_config.exists():
    config_path = bundled_config
else:
    # No config found — passthrough everything
    print("{}", end="")
    sys.exit(0)

run_hook(config_path)
