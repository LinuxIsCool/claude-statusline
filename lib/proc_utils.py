"""Process label resolution for claude-statusline.

Turns generic interpreter names like 'python3' or 'node' into the actual
workload — the script being run, or a known framework keyword. Shared by
cpu_utils (top-RAM list) and gpu_utils (top-VRAM list) so both render
"whisperx" / "ollama" / "comfyui" instead of all-python soup.

Pure stdlib. Never crashes — returns 'unknown' on any failure.

Heuristic order (first match wins):
  1. Well-known framework keyword anywhere in cmdline → that keyword
  2. Interpreter (python/uv/node/bash/...) → script name (basename, no ext)
  3. Non-interpreter executable → argv[0] basename
  4. Fall back to /proc/<pid>/comm
"""

from __future__ import annotations

import re as _re
from pathlib import Path
from typing import List

PROC_ROOT = Path("/proc")

# F20 defense: strip control chars (incl. ESC \x1b) from process labels.
# Linux's PR_SET_NAME accepts arbitrary 16-char byte strings, and argv[0]
# is even less constrained — a process can put ANSI escapes in its name
# to colorize itself in `ps` output. Without this, a malicious or fanciful
# process leaks style into subsequent statusline cells.
_CONTROL_RE = _re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _sanitize_label(label: str) -> str:
    """Remove ANSI escapes, control chars, and any non-printable nasties.

    Strips the full C0/C1 control range (0x00–0x1f, 0x7f–0x9f), which
    covers ESC (0x1b — the leader of every ANSI escape sequence), BEL,
    NUL, line feeds, and DEL. Visible chars like `[31m` may remain
    after an ESC is stripped, but those degrade display, not safety.
    """
    if not label:
        return label
    return _CONTROL_RE.sub("", label)

# Argv[0] names whose first non-flag argument carries the real signal.
_INTERPRETERS = {
    "python", "python2", "python3", "uv", "uvx", "uvicorn",
    "node", "deno", "bun",
    "bash", "sh", "zsh", "fish",
    "ruby", "perl", "pwsh", "lua", "java",
}

# Substrings that, when present in the full cmdline, pin the label.
# Order matters — first hit wins, so put the more-specific patterns first.
_KEYWORDS: List[str] = [
    # Voice / speech
    "whisperx", "faster-whisper", "whisper.cpp", "whisper",
    "kokoro-tts", "kokoro", "piper-tts", "piper",
    "coqui-tts", "tortoise-tts", "bark-tts", "xtts",
    # LLM serving
    "ollama serve", "ollama", "vllm.entrypoints", "vllm",
    "llama-server", "llama.cpp", "llama-cpp", "text-generation-webui",
    # Image / video gen
    "stable-diffusion-webui", "automatic1111", "fooocus", "comfyui", "comfy-ui",
    "invokeai", "kohya_ss",
    # Agent runtimes / Legion services
    "letta-server", "letta",
    "falkordb", "redis-server", "redis",
    "postgres", "postgresql",
    # Transcription pipeline
    "transcribe", "diarize", "pyannote",
    # Browsers (commonly GPU-heavy)
    "firefox", "chrome", "chromium", "brave", "vivaldi",
]


def _basename_no_ext(p: str) -> str:
    name = Path(p).name
    if "." in name and not name.startswith("."):
        name = name.rsplit(".", 1)[0]
    return name


def _read_cmdline(pid: int) -> List[str]:
    cmdline_file = PROC_ROOT / str(pid) / "cmdline"
    if not cmdline_file.exists():
        return []
    try:
        raw = cmdline_file.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return []
    # /proc/<pid>/cmdline uses NUL between args; ignore trailing NUL.
    return [a for a in raw.split("\0") if a]


def _read_comm(pid: int) -> str:
    comm_file = PROC_ROOT / str(pid) / "comm"
    if not comm_file.exists():
        return ""
    try:
        return comm_file.read_text().strip()
    except OSError:
        return ""


def resolve_process_label(pid: int) -> str:
    """Best-effort meaningful label for a PID. Always returns a short string.

    All return paths are sanitized via _sanitize_label so an adversarial or
    fanciful process name (e.g. containing ANSI escapes via PR_SET_NAME or
    argv[0]) can never leak terminal control codes into the statusline.
    """
    args = _read_cmdline(pid)
    full = " ".join(args).lower()

    # 1. Keyword match — most signal-rich path.
    for kw in _KEYWORDS:
        if kw in full:
            return _sanitize_label(kw)

    if args:
        argv0_base = Path(args[0]).name
        # Strip trailing version digits/dots: python3.11 → python
        argv0_stripped = argv0_base
        while argv0_stripped and argv0_stripped[-1] in "0123456789.":
            argv0_stripped = argv0_stripped[:-1]
        argv0_key = argv0_stripped.lower()

        if argv0_key in _INTERPRETERS:
            # 2a. Find the first arg that looks like a script.
            for arg in args[1:]:
                if not arg or arg.startswith("-"):
                    continue
                if (
                    "/" in arg
                    or arg.endswith((".py", ".sh", ".js", ".ts", ".mjs", ".rb", ".lua"))
                ):
                    label = _basename_no_ext(arg)
                    if label:
                        return _sanitize_label(label)
                    break
            # 2b. No script — first non-flag arg, truncated.
            for arg in args[1:]:
                if arg and not arg.startswith("-"):
                    return _sanitize_label(f"{argv0_key}:{Path(arg).name[:20]}")
            return _sanitize_label(argv0_key)

        # 3. Non-interpreter executable.
        return _sanitize_label(argv0_base)

    # 4. Final fallback.
    return _sanitize_label(_read_comm(pid)) or "unknown"


def label_processes(procs: List[dict]) -> List[dict]:
    """In-place relabel a list of {pid, ...} dicts using resolve_process_label."""
    for p in procs:
        try:
            pid = int(p.get("pid", 0))
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        new_label = resolve_process_label(pid)
        if new_label:
            p["name"] = new_label
    return procs
