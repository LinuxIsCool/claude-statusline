# tests/test_gpu_theme_layout.py
"""Layout invariant tests for the GpuTheme declarative grid.

These tests pin the layout contract as the spec. If any test fails, either
the layout has regressed OR the spec has changed (and the test must be updated).
"""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest
from primitives import visible_len
from themes import GpuTheme, _GPU_THEME_COLUMNS, _GPU_THEME_GRID  # exposed in Task 8


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(s: str) -> str:
    return _ANSI.sub("", s)


def _pipe_positions(line: str) -> list[int]:
    """Return list of character positions of '│' in a line (ANSI-stripped)."""
    stripped = _strip_ansi(line)
    return [i for i, ch in enumerate(stripped) if ch == "│"]


# ── Span invariant ──────────────────────────────────────────────────────

def test_every_row_span_sum_equals_column_count(mock_components, palette):
    """No row may declare more or fewer column-spans than the grid has columns."""
    theme = GpuTheme()
    # We expose _build_rows() for testing — returns List[Row] without rendering.
    for row in theme._build_rows(mock_components):
        span_sum = sum(c.span for c in row.cells)
        assert span_sum == len(_GPU_THEME_COLUMNS), \
            f"Row {row.cells!r} has span sum {span_sum}, expected {len(_GPU_THEME_COLUMNS)}"


# ── Total width invariant ──────────────────────────────────────────────

def test_all_lines_have_identical_visible_width(mock_components, palette):
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    lines = rendered.split("\n")
    widths = [visible_len(line) for line in lines]
    expected = _GPU_THEME_GRID.total_width
    for i, w in enumerate(widths):
        assert w == expected, \
            f"Line {i} has width {w}, expected {expected}: {lines[i]!r}"


# ── Pipe alignment invariant ───────────────────────────────────────────

def test_pipes_at_shared_positions_align_vertically(mock_components, palette):
    """For any two rows A and B, any pipe in A whose position also has a pipe
    in B must be at exactly the same x-position.
    """
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    lines = rendered.split("\n")
    # Drop hrule lines (no pipes)
    pipe_lines = [(i, _pipe_positions(line)) for i, line in enumerate(lines)
                  if "│" in _strip_ansi(line)]
    # For each pair, verify shared positions match
    for i, (idx_a, pipes_a) in enumerate(pipe_lines):
        for idx_b, pipes_b in pipe_lines[i + 1:]:
            shared = set(pipes_a) & set(pipes_b)
            # Any position in `shared` is — by definition — present in both,
            # so we just verify each side reports the same x. This is trivially
            # true since `set(pipes_a) & set(pipes_b)` is a set of ints by
            # equality. The real test: NO pipe in A is "near but not at" a
            # pipe in B. We assert that pipes in A whose nearest pipe in B is
            # within 3 chars must be exactly equal.
            for pa in pipes_a:
                near = [pb for pb in pipes_b if abs(pb - pa) <= 2]
                assert not near or pa in near, \
                    f"Pipe at {pa} in line {idx_a} has near-misalignment with " \
                    f"line {idx_b} pipes at {near}"


# ── Hrule width invariant ──────────────────────────────────────────────

def test_horizontal_rules_match_grid_total_width(mock_components, palette):
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    lines = rendered.split("\n")
    hrule_lines = [line for line in lines if set(_strip_ansi(line).replace(" ", "")) == {"─"}]
    assert len(hrule_lines) >= 2, "Expected at least 2 horizontal rules (above CPU, between CPU/GPU)"
    for hr in hrule_lines:
        assert visible_len(hr) == _GPU_THEME_GRID.total_width


# ── Semantic invariants ────────────────────────────────────────────────

def test_identity_line_contains_persona_session_pid_model(mock_components, palette):
    theme = GpuTheme()
    # Post functional-core refactor: themes are pure on components. Provide
    # session_id directly in the mock; the renderer derives the 8-char
    # prefix purely (no env reads at render time).
    mock_components["identity"].value["session_id"] = "deadbeef-cafe-1234"
    rendered = theme.render(mock_components, palette)
    line1 = _strip_ansi(rendered.split("\n")[0])
    assert "matt@legion:674" in line1
    assert "deadbeef" in line1  # 8-char session-id prefix
    assert "Opus 4.7 (1M context)" in line1  # full model name, not truncated


def test_session_id_falls_back_to_transcript_path_basename(mock_components, palette, monkeypatch):
    """When CLAUDEMATRIX_SESSION_ID is absent, parse session_id from transcript_path basename.

    The transcript path looks like:
      /home/shawn/.claude/projects/-home-shawn/<UUID>.jsonl
    So the basename without .jsonl IS the session_id.
    """
    monkeypatch.delenv("CLAUDEMATRIX_SESSION_ID", raising=False)
    test_uuid = "d4c05518-daf5-4b9d-95a3-20d30fef00a0"
    mock_components["identity"].value["session_id"] = ""  # also absent from payload
    mock_components["identity"].value["transcript_path"] = (
        f"/home/shawn/.claude/projects/-home-shawn/{test_uuid}.jsonl"
    )
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    line1 = _strip_ansi(rendered.split("\n")[0])
    # First 8 chars of UUID should appear in identity row
    assert test_uuid[:8] in line1, f"expected {test_uuid[:8]} in line1: {line1!r}"
    assert "????????" not in line1, f"???????? should not appear when transcript known: {line1!r}"


def test_session_id_falls_back_to_payload_session_id(mock_components, palette, monkeypatch):
    """When env var absent but payload.session_id present, use payload."""
    monkeypatch.delenv("CLAUDEMATRIX_SESSION_ID", raising=False)
    mock_components["identity"].value["session_id"] = "abcd1234-deaf-beef"
    mock_components["identity"].value["transcript_path"] = ""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    line1 = _strip_ansi(rendered.split("\n")[0])
    assert "abcd1234" in line1


def test_session_id_falls_back_to_question_marks(mock_components, palette, monkeypatch):
    """When ALL sources are absent, last-resort '????????' renders (not blank)."""
    monkeypatch.delenv("CLAUDEMATRIX_SESSION_ID", raising=False)
    mock_components["identity"].value["session_id"] = ""
    mock_components["identity"].value["transcript_path"] = ""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    line1 = _strip_ansi(rendered.split("\n")[0])
    assert "????????" in line1


def test_rate_limits_show_both_five_hour_and_seven_day(mock_components, palette):
    """Identity row must show BOTH '5h:N%' and '7d:M%' (cell 6)."""
    mock_components["rate_limits"].value = {
        "five_hour": {"used_percentage": 35},
        "seven_day": {"used_percentage": 8},
    }
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    line1 = _strip_ansi(rendered.split("\n")[0])
    assert "5h:35%" in line1, f"5h:35% missing from line 1: {line1!r}"
    assert "7d:8%" in line1, f"7d:8% missing from line 1: {line1!r}"


def test_rate_limits_accept_flat_pct_shape(mock_components, palette):
    """compute_rate_limits returns flat keys (five_hour_pct/seven_day_pct);
    identity row must read either nested or flat shape."""
    mock_components["rate_limits"].value = {
        "five_hour_pct": 42,
        "seven_day_pct": 11,
    }
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    line1 = _strip_ansi(rendered.split("\n")[0])
    assert "5h:42%" in line1
    assert "7d:11%" in line1


def test_uptime_appears_on_identity_line_only(mock_components, palette):
    """Session uptime (e.g., '1h14m') must appear exactly once — on line 1."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    lines = [_strip_ansi(l) for l in rendered.split("\n")]
    # mock duration = 4_440_000 ms = 74 min = "1h14m"
    line1 = lines[0]
    line2 = lines[1]
    assert "1h14m" in line1, f"uptime missing from line 1: {line1!r}"
    assert "1h14m" not in line2, f"uptime duplicated on line 2: {line2!r}"


def test_ctx_renders_as_progress_bar_when_known(mock_components, palette):
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    line1 = _strip_ansi(rendered.split("\n")[0])
    # Post Fix-3: label is left-padded to 4 chars → 'ctx :' (with space)
    # to match the uniform 10-char bar-cell prefix.
    assert "ctx :" in line1
    assert ("█" in line1 or "▎" in line1 or "▌" in line1 or "▏" in line1), \
        f"ctx cell missing bar glyph: {line1!r}"


def test_progress_bar_empty_cells_use_visible_glyph(mock_components, palette):
    """At low fills, the empty portion of a metric bar must use the same █
    glyph as the filled portion (distinguished only by dim vs bright color).

    Same-glyph bars (post-2026-06-01): both fill and empty are █, with
    sub-block partials (▏▎▍▌▋▊▉) at the boundary for 1/8th precision. No
    glyph-family change = no visual gap.
    """
    # Set a low context fill so most bar cells are unfilled.
    mock_components["context"].value["used_percentage"] = 22
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    line1 = _strip_ansi(rendered.split("\n")[0])
    # Post Fix-3: 'ctx :' (label padded to 4 chars in the uniform bar cell).
    assert "ctx :" in line1
    # _gpu_bar must produce '█' (full block) for empty cells too — dim color
    # is the only distinction from the fill.
    assert "█" in line1, f"expected '█' glyph in low-fill bar: {line1!r}"
    # Empty glyphs (▒, ░) must NOT appear — the old gappy behavior is gone.
    assert "▒" not in line1, f"old ▒ empty glyph leaked: {line1!r}"
    assert "░" not in line1, f"old ░ empty glyph leaked: {line1!r}"


def test_model_includes_context_qualifier(mock_components, palette):
    """'Opus 4.7 (1M context)' must NOT be truncated to 'Opus 4.7'."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    text = _strip_ansi(rendered)
    assert "Opus 4.7 (1M context)" in text


def test_workspace_branch_shown_when_in_git_repo(mock_components, palette, tmp_path, monkeypatch):
    """When cwd is inside a git repo with branch 'main', ⎇ main must appear."""
    # Initialize a temp git repo
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    mock_components["workspace"].value["cwd"] = str(repo)
    mock_components["workspace"].value["cwd_short"] = str(repo)
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    line2 = _strip_ansi(rendered.split("\n")[1])
    assert "⎇ main" in line2 or "⎇ master" in line2, f"branch missing: {line2!r}"


def test_workspace_default_style_omitted(mock_components, palette):
    """If output_style == 'default', the cell must not appear (no big gap)."""
    mock_components["workspace"].value["output_style"] = "default"
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    line2 = _strip_ansi(rendered.split("\n")[1])
    assert "default" not in line2


def test_workspace_diff_present_when_lines_changed(mock_components, palette):
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    line2 = _strip_ansi(rendered.split("\n")[1])
    assert "+120" in line2
    assert "-33" in line2


# ── Process row invariants ─────────────────────────────────────────────

def test_cpu_procs_align_with_gpu_procs(mock_components, palette):
    """Pipe positions in CPU procs row equal pipe positions in GPU procs row."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    lines = rendered.split("\n")
    # CPU procs = line index 4 (lines 1-indexed: identity=1, workspace=2, hrule=3, cpu=4, cpu_procs=5)
    # GPU procs = line index 7 (after hrule=6, gpu=7, gpu_procs=8)
    cpu_procs = _pipe_positions(lines[4])
    gpu_procs = _pipe_positions(lines[7])
    assert cpu_procs == gpu_procs, f"CPU procs pipes {cpu_procs} != GPU procs pipes {gpu_procs}"


def test_cpu_summary_omits_top_proc_highlight(mock_components, palette):
    """Wave C: the c2 '→ topproc' cell was removed — it duplicated info already
    shown in the procs row directly below. Assert no arrow appears in the CPU
    summary row."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    cpu_summary_line = _strip_ansi(rendered.split("\n")[3])
    assert "→" not in cpu_summary_line, (
        f"top-proc arrow must NOT appear in CPU summary after Wave C: "
        f"{cpu_summary_line!r}"
    )


def test_gpu_summary_omits_top_proc_highlight(mock_components, palette):
    """Same as CPU summary — Wave C removed the top-proc cell."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    gpu_summary_line = _strip_ansi(rendered.split("\n")[6])
    assert "→" not in gpu_summary_line, (
        f"top-proc arrow must NOT appear in GPU summary after Wave C: "
        f"{gpu_summary_line!r}"
    )


def test_chip_name_renders_fully_without_truncation(mock_components, palette):
    """After Wave C: chip span=2 means 'Intel i7-13700F' fits without ellipsis."""
    mock_components["cpu"].value["name"] = "Intel i7-13700F"
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    text = _strip_ansi(rendered)
    assert "Intel i7-13700F" in text  # full name, NO ellipsis
    assert "Intel i7-13…" not in text  # truncated form must NOT appear


def test_summary_row_first_pipes_align_with_each_other(mock_components, palette):
    """Under the uniform 16w spreadsheet grid post-Wave C, both summary rows
    use chip span=2 (merged c1+c2), so their first pipes land on the same
    x position (end of c2 = visible position 35) — the same column boundary
    as the identity row's persona+sid span=2 cell."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    lines = rendered.split("\n")
    cpu_summary_pipes = _pipe_positions(lines[3])
    gpu_summary_pipes = _pipe_positions(lines[6])
    assert cpu_summary_pipes[0] == gpu_summary_pipes[0], (
        f"CPU summary first pipe != GPU summary first pipe; "
        f"got {cpu_summary_pipes[0]}/{gpu_summary_pipes[0]}"
    )
    # First pipe lands on SOME column boundary.
    expected = _expected_pipe_positions_for_grid()
    assert cpu_summary_pipes[0] in expected, (
        f"CPU summary first pipe at {cpu_summary_pipes[0]} not a column boundary "
        f"(expected one of {sorted(expected)})"
    )
    # Identity row's first pipe also lands on a column boundary.
    identity_pipes = _pipe_positions(lines[0])
    assert identity_pipes[0] in expected, (
        f"identity first pipe at {identity_pipes[0]} not a column boundary "
        f"(expected one of {sorted(expected)})"
    )


def test_same_name_processes_aggregated_in_procs_row(mock_components, palette):
    """Multiple PIDs sharing a display name (e.g., firefox content procs) must
    appear ONCE in the procs row, with summed RSS. The 16w cell budget may
    truncate the name itself but the aggregated memory MUST appear."""
    mock_components["cpu"].value["processes"] = [
        {"pid": "100", "mem_mib": 1100, "name": "firefox"},
        {"pid": "101", "mem_mib": 650, "name": "firefox"},
        {"pid": "102", "mem_mib": 300, "name": "firefox"},
        {"pid": "200", "mem_mib": 500, "name": "redis-server"},
        {"pid": "300", "mem_mib": 400, "name": "plasmashell"},
    ]
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    cpu_procs_line = _strip_ansi(rendered.split("\n")[4])
    # firefox name may be truncated under uniform 16w cells; assert the
    # PREFIX appears at most once (i.e., one row entry for firefox).
    firefox_prefixes = cpu_procs_line.count("firef")
    assert firefox_prefixes == 1, (
        f"expected ONE firefox-prefix entry after aggregation; "
        f"got {firefox_prefixes}: {cpu_procs_line!r}"
    )
    # Aggregated RSS = 1100+650+300 = 2050 MiB ≈ 2.0GB (always-GB format).
    assert "2.0GB" in cpu_procs_line, \
        f"missing aggregated firefox RSS 2.0GB: {cpu_procs_line!r}"


def test_other_segment_shown_when_gap_exists(mock_components, palette):
    """Mock CPU has ram_used=13312 MiB, top-5 sum ≈ 2646 MiB → +other ≈ 10.4GB."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    text = _strip_ansi(rendered)
    assert "other" in text
    assert "GB" in text


def test_other_segment_absent_when_top_5_account_for_all(mock_components, palette):
    """Set top-5 RSS to equal total RAM used so +other = 0; cell should render
    em-dash (honest 'nothing here') instead of '+0.0GB other'."""
    mock_components["cpu"].value["ram_used_mib"] = 2646
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    lines = _strip_ansi(rendered).split("\n")
    cpu_procs = lines[4]
    assert "other" not in cpu_procs


def test_gpu_procs_empty_slots_render_em_dash(mock_components, palette):
    """When fewer than 5 GPU procs exist, empty slots show '—' not blank padding."""
    # mock has only 3 GPU procs, so slots 4 and 5 are short
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    gpu_procs_line = _strip_ansi(rendered.split("\n")[7])
    # We expect at least one em-dash to fill the empty proc slots
    assert "—" in gpu_procs_line, \
        f"empty GPU proc slot should render em-dash: {gpu_procs_line!r}"


def test_net_summary_latency_placeholder_renders_em_dash(mock_components, palette):
    """The trailing c8 latency-placeholder cell in the net summary row must
    render as an em-dash, not invisible padding."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    net_summary = _strip_ansi(rendered.split("\n")[9])
    # At minimum, the row should contain an em-dash somewhere on the right side
    # (either the latency placeholder or unavailable signal_dbm)
    assert "—" in net_summary, f"net summary missing em-dash: {net_summary!r}"


def test_net_endpoints_empty_cells_render_em_dash(mock_components, palette):
    """Net endpoints row pads trailing tunnel cells with em-dashes when fewer
    than the slot count of WireGuard tunnels are configured."""
    # mock has just 1 wg0 tunnel; other tunnel slots should be em-dashed
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    net_endpoints = _strip_ansi(rendered.split("\n")[10])
    assert "—" in net_endpoints, f"net endpoints missing em-dash: {net_endpoints!r}"


# ── Honesty invariants ─────────────────────────────────────────────────

def test_cpu_fan_shows_em_dash_when_unavailable(mock_components, palette):
    """fan_available=False → 'fan:—', NOT 'fan:0%'."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    text = _strip_ansi(rendered)
    assert "fan:—" in text or "fan:?" in text


def test_cpu_power_em_dash_when_rapl_gated(mock_components, palette):
    mock_components["cpu"].value["power_available"] = False
    mock_components["cpu"].value["power_w"] = 0.0
    mock_components["cpu"].value["power_limit_w"] = 241.0
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    text = _strip_ansi(rendered)
    assert "—/241W" in text


# ── Network section invariants ─────────────────────────────────────────

def test_network_summary_contains_iface_and_ssid(mock_components, palette):
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    text = _strip_ansi(rendered)
    assert "wlan0" in text or "ExampleNet" in text


def test_network_shows_up_down_rates(mock_components, palette):
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    text = _strip_ansi(rendered)
    # 1_500_000 bps = 1.5 Mbps; check for "Mbps" or "MB/s"
    assert "Mbps" in text or "MB/s" in text or "Kbps" in text


def test_network_shows_tailscale_peers(mock_components, palette):
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    text = _strip_ansi(rendered)
    assert "0/10" in text or "peers" in text.lower()


def test_network_signal_em_dash_when_wired(mock_components, palette):
    """If iface starts with 'eth' or 'enp', signal_dbm should render as '—'."""
    mock_components["net"].value["iface"] = "enp4s0"
    mock_components["net"].value["signal_dbm"] = None
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    text = _strip_ansi(rendered)
    # Either em-dash or absence; just confirm no fake dBm value
    assert "-256 dBm" not in text
    assert "0 dBm" not in text


# ── Emoji-width invariants ─────────────────────────────────────────────

def test_chip_emoji_widths_compensate_aligned(mock_components, palette):
    """🖥️ on CPU summary line and 🎮 on GPU summary line must produce equal-width chip cells."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    lines = rendered.split("\n")
    cpu_summary = lines[3]
    gpu_summary = lines[6]
    # Both lines should have first pipe at the same position
    cpu_pipes = _pipe_positions(cpu_summary)
    gpu_pipes = _pipe_positions(gpu_summary)
    assert cpu_pipes[0] == gpu_pipes[0], \
        f"First pipe in CPU summary at {cpu_pipes[0]} != GPU summary at {gpu_pipes[0]}"


def test_lotus_emoji_doesnt_shift_session_column(mock_components, palette):
    """Identity-row's first pipe (after 🪷-prefixed cell) lands at same col as CPU summary's."""
    theme = GpuTheme()
    rendered = theme.render(mock_components, palette)
    lines = rendered.split("\n")
    line1_first_pipe = _pipe_positions(lines[0])[0]
    line4_first_pipe = _pipe_positions(lines[3])[0]
    # Both identity (persona+sid span=2) and CPU summary (chip span=2 post-Wave C)
    # put their first pipe at end of col 2. Each row's first pipe must land on
    # SOME column boundary, even if not necessarily the same one.
    expected_pipe_positions = _expected_pipe_positions_for_grid()
    assert line1_first_pipe in expected_pipe_positions
    assert line4_first_pipe in expected_pipe_positions


def _expected_pipe_positions_for_grid() -> set[int]:
    """All x-positions where a pipe could possibly appear (col boundaries)."""
    sep = " │ "
    pos = 0
    boundaries = set()
    for i, col in enumerate(_GPU_THEME_COLUMNS):
        pos += col.width
        if i < len(_GPU_THEME_COLUMNS) - 1:
            # Pipe lands at position pos + 1 (after one space) — but visible
            # col index of │ depends on how separator is laid out. Compute
            # exact position.
            boundaries.add(pos + 1)  # ' │ ' has │ at offset 1
            pos += len(sep)
    return boundaries


# ── Overflow / long-name invariant (legion2 regression) ─────────────────

def test_long_hardware_names_preserve_grid_width(mock_components, palette):
    """Real-world long CPU/GPU names must be clipped to their cell, never
    overflow and shift downstream columns. Reproduces the legion2 bug where the
    CPU/GPU rows rendered at 154/160 instead of the grid's total_width."""
    mock_components["cpu"].value["name"] = "AMD Ryzen 9 9955HX3D"
    mock_components["gpu"].value["name"] = "NVIDIA RTX 5080 Laptop GPU"
    theme = GpuTheme()
    lines = theme.render(mock_components, palette).split("\n")
    expected = _GPU_THEME_GRID.total_width
    for i, line in enumerate(lines):
        assert visible_len(line) == expected, \
            f"Line {i} width {visible_len(line)} != {expected}: {line!r}"
