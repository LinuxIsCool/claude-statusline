---
name: selftest
description: "Verify claude-statusline runtime capabilities (deps, /proc, binaries, themes, render)"
allowed-tools: ["Bash"]
---

# /statusline:selftest

Run the claude-statusline runtime canary. Confirms every dependency the
statusline needs at render time is present and callable on this host:

- Python + `wcwidth`
- `/proc/stat`, `/proc/meminfo`, `/proc/net/dev`, `/proc/net/wireless`
- `/sys/class/hwmon/`
- `nvidia-smi`, `tailscale`, `nmcli`, `git rev-parse`
- All `hooks/*.py` import without error
- Every theme in `THEME_REGISTRY` constructs
- A synthetic payload renders to non-empty output through `hooks/status.py`

Exit code is 0 if all green, 1 if any check failed. Warnings (e.g. wcwidth
absent but defensive fallback active) do not fail the run.

## Implementation

Run the selftest script via uv (PEP-723 deps installed on demand):

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/hooks/selftest.py"
```

For machine-readable output:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/hooks/selftest.py" --json
```

Report the result back to the user verbatim, including the final
`N warning(s), M failure(s)` summary line. If any failures, surface the
offending lines first so the user can act.
