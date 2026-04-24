---
name: less-permission-prompts
description: Measure permission coverage and auto-patch config.toml to close the gaps until recall hits 95%. Reads history, runs confusion matrix, proposes allow/ask/deny rules for uncovered commands, and applies them after user approval.
---

Take the user from "too many permission prompts" to a config that auto-approves ≥95% of their actual workflow. This skill measures current coverage, proposes patterns for the biggest gaps, and applies them after the user reviews the diff.

## Arguments

`$ARGUMENTS` may contain:
- `--target N` — recall target (default: 95)
- `--max-per-round N` — patterns to propose per pass (default: 10)
- `--auto` — skip confirmation and apply automatically
- `--measure-only` — run confusion matrix and stop (no proposal, no write)

## Step 1: Locate the user config

Check for `~/.config/claude-permissions-pro/config.toml`. This is where user edits live.

```bash
USER_CONFIG="$HOME/.config/claude-permissions-pro/config.toml"
```

If it doesn't exist, bootstrap one from history:

```bash
PROJECT_ROOT="${CLAUDE_PLUGIN_ROOT:-$HOME/claude-permissions-pro}"
PYTHONPATH="$PROJECT_ROOT/src:$PYTHONPATH" \
  python3 -m claude_permissions_pro.cli init -o "$USER_CONFIG"
```

Tell the user this happened — they have a fresh config now, seeded from their command history.

## Step 2: Measure current coverage

Run the confusion matrix against the user config:

```bash
PROJECT_ROOT="${CLAUDE_PLUGIN_ROOT:-$HOME/claude-permissions-pro}"
PYTHONPATH="$PROJECT_ROOT/src:$PYTHONPATH" \
  python3 -m claude_permissions_pro.cli confusion-matrix -c "$USER_CONFIG"
```

Parse the output for:
1. **Recall %** (e.g. "Recall (auto-approve rate): 87.3%")
2. **Top uncovered commands** — the `fn_by_command` breakdown
3. **Sample false negatives** — actual command strings

Report the current recall to the user before moving on. If `--measure-only` was set, stop here.

## Step 3: Decide if action is needed

If recall ≥ target, print:
```
Recall is N% (target: 95%). Already there — no changes needed.
```
...and exit. Done.

Otherwise proceed.

## Step 4: Classify uncovered commands

For each of the top `--max-per-round` uncovered base commands (or until you've covered enough to cross the target), classify it into one of four buckets:

| Bucket | When | Output |
|--------|------|--------|
| **ALLOW** | Safe read-only or routine dev command. Same risk class as commands already in config. | `[[allow]] pattern = "foo *"` |
| **ASK** | Useful but sometimes destructive (e.g. `rm`, `psql` with DML). | `[[ask]] pattern = "foo *"` |
| **DENY** | Never run unsupervised (e.g. `shutdown`, `dd`). | `[[deny]] pattern = "foo *"` (and flag for user) |
| **SKIP** | Parser artifact, not a real command. Examples: `EOF`, `const`, `{}))`, `1 *`, `}`. | No pattern; note it for the user |

**Safety rules when classifying:**

- **Follow this project's existing risk tolerance, not a generic one.** If `config.toml` already allowlists `python3 *`, `bash *`, `uv *`, that's the user's deliberate choice. Match that precedent. Don't import a stricter policy from elsewhere.
- **Never modify `[[deny]]` silently.** If you'd recommend a deny, call it out and wait for the user to confirm.
- **Skip parser garbage.** If the top FN entries look like heredoc fragments or JS tokens (`EOF`, `const`, `}`, `)`, etc.), don't propose patterns for them — flag them as a parser issue the user may want to look at.
- **Don't widen past what's observed.** If the user only ran `foo status`, `Bash(foo status *)` beats `Bash(foo *)`.
- **Check dedup before proposing.** If `config.toml` already has an entry that would cover the command, skip it (there's probably a subtle matcher bug in that case — flag it).

## Step 5: Present the proposed patch

Before writing anything, show the user a preview:

```
Proposed additions to ~/.config/claude-permissions-pro/config.toml:

  [[allow]]
  pattern = "foo *"   # 42 FN, e.g. "foo bar --baz"

  [[ask]]
  pattern = "rm -rf *"   # 12 FN, destructive

Skipped (parser artifacts):
  EOF (31x), const (18x), })) (16x)

Estimated recall after apply: ~93.5% (+6.2pp)

Apply? [y/n]
```

If `--auto` is set, skip the prompt. Otherwise wait for user confirmation.

## Step 6: Apply the patch

Append approved blocks to the user's config using the Edit tool. Preserve all existing content.

- Add a section header comment so future-you can find the block: `# Added by /less-permission-prompts on YYYY-MM-DD`
- Put `[[allow]]` entries near the other allows, `[[ask]]` near the asks, `[[deny]]` near the denies
- Dedupe: if the exact `pattern = "..."` line already exists anywhere in the file, skip it

## Step 7: Re-measure and report

Run `confusion-matrix` again. Report:

```
Before: 87.3% recall
After:  94.1% recall (+6.8pp)

Still uncovered: 142 commands (top: docker-compose, kubectl, ansible)
Run /less-permission-prompts again to keep closing gaps.
```

If the target was met, say so explicitly. If it wasn't but progress was made, suggest another pass.

## Edge cases

- **Config exists but is malformed.** If `init` or `confusion-matrix` errors on parse, surface the error — don't try to auto-fix it, let the user decide.
- **No history yet.** If `analyze` / `confusion-matrix` finds zero commands, tell the user this skill needs session history to work. Nothing to do on a fresh install.
- **Target already met.** Report and stop; don't invent problems.
- **User declined the patch.** Don't apply anything. Exit cleanly.
