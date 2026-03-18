---
name: confusion
description: Run confusion matrix analysis to measure config accuracy (recall, false negatives, coverage gaps)
---

Run the confusion matrix analysis against the user's session history and decision log.

```bash
source /home/duane/claude-permissions-pro/.venv/bin/activate && claude-permissions-pro confusion-matrix -c /home/duane/claude-permissions-pro/config.toml $ARGUMENTS
```

After the output, analyze the results:
1. **Recall** — what % of the user's normal workflow is auto-approved
2. **False negatives** — commands the user had to manually approve (coverage gaps)
3. **Top uncovered commands** — which base commands need patterns added to config.toml
4. **Judge overrides** — if decision log data exists, highlight commands where the judge said no but the user said yes (these are judge tuning opportunities)

If recall is below 95%, suggest specific patterns to add to config.toml to close the gap.
