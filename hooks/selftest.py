#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "wcwidth>=0.2.0",
# ]
# ///
"""claude-statusline — runtime capability selftest.

Verifies that every dependency the statusline relies on at render time is
present and callable on this host. Prints a colorized checklist to stdout
and exits 0 if all green, 1 if any check failed. Warnings (e.g. wcwidth
unavailable but defensive fallback active) do not fail the run.

Usage:
    uv run hooks/selftest.py
    uv run hooks/selftest.py --json
    uv run hooks/selftest.py --quiet

Designed to be wired into a slash command (/statusline:selftest) so an
operator can confirm a healthy substrate before debugging cosmetic output.
"""

from __future__ import annotations

import argparse
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# ── Paths ──────────────────────────────────────────────────────────
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LIB_DIR = PLUGIN_ROOT / "lib"
HOOKS_DIR = PLUGIN_ROOT / "hooks"
sys.path.insert(0, str(LIB_DIR))


# ── Colors (TTY-aware) ─────────────────────────────────────────────
class _Colors:
    def __init__(self, enabled: bool) -> None:
        if enabled:
            self.GREEN = "\033[32m"
            self.RED = "\033[31m"
            self.YELLOW = "\033[33m"
            self.DIM = "\033[2m"
            self.BOLD = "\033[1m"
            self.RST = "\033[0m"
        else:
            self.GREEN = self.RED = self.YELLOW = ""
            self.DIM = self.BOLD = self.RST = ""


# ── Result accumulator ─────────────────────────────────────────────
class Result:
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"

    def __init__(self, name: str, status: str, message: str = "") -> None:
        self.name = name
        self.status = status
        self.message = message


class Report:
    def __init__(self) -> None:
        self.results: List[Result] = []

    def ok(self, name: str, message: str = "") -> None:
        self.results.append(Result(name, Result.OK, message))

    def warn(self, name: str, message: str = "") -> None:
        self.results.append(Result(name, Result.WARN, message))

    def fail(self, name: str, message: str = "") -> None:
        self.results.append(Result(name, Result.FAIL, message))

    @property
    def failures(self) -> int:
        return sum(1 for r in self.results if r.status == Result.FAIL)

    @property
    def warnings(self) -> int:
        return sum(1 for r in self.results if r.status == Result.WARN)

    def exit_code(self) -> int:
        return 1 if self.failures else 0


# ── Individual checks ──────────────────────────────────────────────
def check_python(report: Report) -> None:
    v = sys.version_info
    report.ok("Python", f"{v.major}.{v.minor}.{v.micro}")


def check_wcwidth(report: Report) -> None:
    try:
        import wcwidth  # type: ignore[import-not-found]

        version = getattr(wcwidth, "__version__", "unknown")
        report.ok("wcwidth", f"{version} available")
    except ImportError as e:
        # primitives.py has a defensive fallback, so this is a warning
        report.warn("wcwidth", f"not installed (defensive fallback active): {e}")


def check_readable_file(report: Report, path: str) -> None:
    p = Path(path)
    try:
        if not p.exists():
            report.fail(path, "missing")
            return
        with open(p, "rb") as f:
            f.read(64)
        report.ok(path, "readable")
    except Exception as e:
        report.fail(path, f"unreadable: {e}")


def check_readable_dir(report: Report, path: str) -> None:
    p = Path(path)
    try:
        if not p.exists():
            report.fail(path, "missing")
            return
        if not p.is_dir():
            report.fail(path, "not a directory")
            return
        # Best effort listing — succeed if we can enumerate at all
        entries = list(p.iterdir())
        report.ok(path, f"{len(entries)} entries")
    except PermissionError as e:
        report.fail(path, f"permission denied: {e}")
    except Exception as e:
        report.fail(path, f"unreadable: {e}")


def check_subprocess(
    report: Report,
    name: str,
    cmd: List[str],
    timeout: float = 1.0,
    success_extractor: Optional[Callable[[str], str]] = None,
    required: bool = True,
) -> None:
    """Run a subprocess and record success/failure.

    If ``required`` is False, a missing binary is downgraded from FAIL to WARN.
    """
    binary = cmd[0]
    if shutil.which(binary) is None:
        msg = f"{binary} not callable: command not found"
        (report.fail if required else report.warn)(name, msg)
        return
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        report.fail(name, f"{binary} timed out after {timeout}s")
        return
    except Exception as e:
        report.fail(name, f"{binary} raised: {e}")
        return
    if out.returncode != 0:
        stderr = (out.stderr or "").strip().splitlines()
        detail = stderr[0] if stderr else f"exit {out.returncode}"
        report.fail(name, f"{binary} exit {out.returncode}: {detail}")
        return
    detail = "callable"
    if success_extractor:
        try:
            detail = success_extractor(out.stdout)
        except Exception:
            detail = "callable"
    report.ok(name, detail)


def check_hook_imports(report: Report) -> None:
    """Make sure each hook script can be imported as a module without crashing."""
    hooks = [
        "status.py",
        "session_start.py",
        "session_stop.py",
        "user_prompt.py",
        "grid_tool.py",
    ]
    failed: List[str] = []
    for hook in hooks:
        path = HOOKS_DIR / hook
        if not path.exists():
            failed.append(f"{hook} (missing)")
            continue
        # Load source and compile — running it would trigger main() via __main__,
        # which is undesirable. Compiling catches import-time syntax/name errors;
        # we additionally exec the module body with __name__ != "__main__" to
        # surface any top-level import failures.
        try:
            source = path.read_text()
            code = compile(source, str(path), "exec")
            module_globals: dict = {
                "__name__": f"_selftest_{path.stem}",
                "__file__": str(path),
            }
            buf = io.StringIO()
            with redirect_stderr(buf), redirect_stdout(buf):
                exec(code, module_globals)
        except SystemExit:
            # Some hooks may sys.exit() in defensive guards — treat as import-clean
            pass
        except Exception as e:
            failed.append(f"{hook}: {type(e).__name__}: {e}")
    if failed:
        report.fail("hook imports", "; ".join(failed))
    else:
        report.ok("hook imports", f"{len(hooks)} hooks loadable")


def check_themes_construct(report: Report) -> None:
    """Re-import lib/themes and confirm every theme in THEME_REGISTRY is a Theme instance."""
    try:
        import themes  # type: ignore[import-not-found]

        registry = getattr(themes, "THEME_REGISTRY", None)
        if not registry:
            report.fail("themes", "THEME_REGISTRY missing or empty")
            return
        theme_cls = getattr(themes, "Theme", None)
        if theme_cls is None:
            report.fail("themes", "Theme base class missing")
            return
        bad = [t for t in registry if not isinstance(t, theme_cls)]
        if bad:
            report.fail("themes", f"{len(bad)} entries are not Theme instances")
            return
        # Also verify each declares a non-empty name (sanity)
        unnamed = [t for t in registry if not getattr(t, "name", "")]
        if unnamed:
            report.fail("themes", f"{len(unnamed)} themes have no name")
            return
        report.ok("themes", f"{len(registry)} themes constructed")
    except Exception as e:
        report.fail("themes", f"{type(e).__name__}: {e}")


def check_status_render(report: Report) -> None:
    """Pipe a synthetic payload into hooks/status.py and confirm we get non-empty output."""
    status_script = HOOKS_DIR / "status.py"
    if not status_script.exists():
        report.fail("status render", "hooks/status.py missing")
        return
    payload = {
        "session_id": "selftest-0000-0000-0000-000000000000",
        "transcript_path": "/tmp/selftest-transcript.jsonl",
        "cwd": str(PLUGIN_ROOT),
        "model": {"id": "claude-opus-4-7", "display_name": "Opus 4.7 (selftest)"},
        "cost": {"total_cost_usd": 0.0, "total_duration_ms": 0},
        "context_window": {"used_percentage": 0, "remaining_percentage": 100},
        "agent_type": "claude-personas:legion",
    }
    try:
        proc = subprocess.run(
            ["uv", "run", str(status_script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=20.0,
        )
    except subprocess.TimeoutExpired:
        report.fail("status render", "timed out (>20s)")
        return
    except Exception as e:
        report.fail("status render", f"{type(e).__name__}: {e}")
        return

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        detail = stderr[-1] if stderr else f"exit {proc.returncode}"
        report.fail("status render", detail)
        return
    out = proc.stdout or ""
    if not out.strip():
        report.fail("status render", "empty output")
        return
    if "Traceback" in (proc.stderr or "") or "Traceback" in out:
        report.fail("status render", "traceback in output")
        return
    lines = out.splitlines()
    report.ok("status render", f"{len(lines)} line(s) rendered for synthetic payload")


# ── nvidia-smi / tailscale / nmcli extractors ──────────────────────
def _ts_peer_count(stdout: str) -> str:
    # `tailscale status` prints one peer per line after the self line
    lines = [ln for ln in stdout.splitlines() if ln.strip() and not ln.startswith("#")]
    # Subtract 1 for the self entry if multiple lines
    peers = max(len(lines) - 1, 0)
    return f"callable ({peers} peers)"


def _nmcli_device_count(stdout: str) -> str:
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    # First line is header
    devices = max(len(lines) - 1, 0)
    return f"callable ({devices} devices)"


def _nvidia_gpu_summary(stdout: str) -> str:
    rows = [r.strip() for r in stdout.strip().splitlines() if r.strip()]
    return f"callable ({len(rows)} GPU(s))"


def _git_short(stdout: str) -> str:
    return f"callable (HEAD: {stdout.strip()[:12] or 'unknown'})"


# ── Output rendering ───────────────────────────────────────────────
def print_text_report(report: Report, colors: _Colors) -> None:
    for r in report.results:
        if r.status == Result.OK:
            mark = f"{colors.GREEN}[OK]{colors.RST}"
        elif r.status == Result.WARN:
            mark = f"{colors.YELLOW}[!]{colors.RST}"
        else:
            mark = f"{colors.RED}[X]{colors.RST}"
        label = f"{colors.BOLD}{r.name}{colors.RST}"
        suffix = f" {colors.DIM}— {r.message}{colors.RST}" if r.message else ""
        print(f"{mark} {label}{suffix}")

    print()
    summary_color = (
        colors.RED
        if report.failures
        else (colors.YELLOW if report.warnings else colors.GREEN)
    )
    summary = (
        f"{summary_color}{report.warnings} warning(s), "
        f"{report.failures} failure(s){colors.RST}"
    )
    print(summary)


def print_json_report(report: Report) -> None:
    payload = {
        "exit_code": report.exit_code(),
        "failures": report.failures,
        "warnings": report.warnings,
        "results": [
            {"name": r.name, "status": r.status, "message": r.message}
            for r in report.results
        ],
    }
    print(json.dumps(payload, indent=2))


# ── Main ───────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify claude-statusline runtime capabilities on this host."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of human-readable output."
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress non-failure output (still exits with code)."
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable ANSI color even if stdout is a TTY."
    )
    args = parser.parse_args()

    colors = _Colors(
        enabled=(sys.stdout.isatty() and not args.no_color and not args.json)
    )

    report = Report()

    # 1. Python + wcwidth
    check_python(report)
    check_wcwidth(report)

    # 2. /proc + /sys files the statusline reads
    check_readable_file(report, "/proc/stat")
    check_readable_file(report, "/proc/meminfo")
    check_readable_file(report, "/proc/net/dev")
    # /proc/net/wireless may not exist on hosts without wireless — warn, don't fail
    if Path("/proc/net/wireless").exists():
        check_readable_file(report, "/proc/net/wireless")
    else:
        report.warn("/proc/net/wireless", "not present (no wireless interface)")
    check_readable_dir(report, "/sys/class/hwmon/")

    # 3. External binaries
    check_subprocess(
        report,
        "nvidia-smi",
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        timeout=1.0,
        success_extractor=_nvidia_gpu_summary,
        required=False,  # optional integration: missing tool is WARN, not FAIL
    )
    check_subprocess(
        report,
        "tailscale",
        ["tailscale", "status", "--peers=true", "--self=true"],
        timeout=1.0,
        success_extractor=_ts_peer_count,
        required=False,  # optional integration: missing tool is WARN, not FAIL
    )
    check_subprocess(
        report,
        "nmcli",
        ["nmcli", "-t", "-f", "DEVICE", "device", "status"],
        timeout=1.0,
        success_extractor=_nmcli_device_count,
        required=False,  # optional integration: missing tool is WARN, not FAIL
    )
    check_subprocess(
        report,
        "git rev-parse",
        ["git", "rev-parse", "--short", "HEAD"],
        timeout=2.0,
        success_extractor=_git_short,
        required=True,
    )

    # 4. Hook scripts compile + import cleanly
    check_hook_imports(report)

    # 5. Theme registry constructs
    check_themes_construct(report)

    # 6. Synthetic render through hooks/status.py
    check_status_render(report)

    # Emit
    if args.json:
        print_json_report(report)
    elif args.quiet:
        # Still show failures, otherwise stay silent
        if report.failures:
            for r in report.results:
                if r.status == Result.FAIL:
                    print(f"[X] {r.name}: {r.message}", file=sys.stderr)
    else:
        print_text_report(report, colors)

    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
