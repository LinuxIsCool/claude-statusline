#!/usr/bin/env bash
# Install KDE Plasma 6 keyboard shortcut for statusline theme cycling.
# Ctrl+Shift+T → cycle to next theme
#
# Idempotent — safe to re-run. Self-detecting — warns if not KDE.
# Uses kwriteconfig6 to register a custom shortcut.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CYCLE_SCRIPT="${SCRIPT_DIR}/cycle_theme.py"
SHORTCUT_NAME="StatuslineThemeCycle"
SHORTCUT_KEY="Ctrl+Shift+T"
COLOR_SHORTCUT_NAME="StatuslineColorCycle"
COLOR_SHORTCUT_KEY="Ctrl+Shift+C"

# ── Check prerequisites ──────────────────────────────────────────────

if [ -z "${XDG_CURRENT_DESKTOP:-}" ] || [[ ! "$XDG_CURRENT_DESKTOP" == *"KDE"* ]]; then
    echo "⚠ Not running KDE Plasma. This installer is for KDE only."
    echo "  Detected: XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-unset}"
    echo ""
    echo "  For other DEs, run the cycle script directly:"
    echo "    python3 ${CYCLE_SCRIPT}"
    exit 1
fi

if ! command -v kwriteconfig6 &>/dev/null; then
    echo "⚠ kwriteconfig6 not found. Are you on Plasma 6?"
    exit 1
fi

if [ ! -f "$CYCLE_SCRIPT" ]; then
    echo "⚠ cycle_theme.py not found at: $CYCLE_SCRIPT"
    exit 1
fi

# ── Register shortcut ────────────────────────────────────────────────

CONFIG_FILE="$HOME/.config/kglobalshortcutsrc"
DESKTOP_FILE="$HOME/.local/share/applications/statusline-theme-cycle.desktop"

# Create .desktop file (required for KDE custom shortcuts)
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Statusline Theme Cycle
Comment=Cycle claude-statusline theme (next)
Exec=python3 ${CYCLE_SCRIPT} next
Terminal=false
Type=Application
Categories=Utility;
NoDisplay=true
EOF

echo "✓ Created desktop entry: $DESKTOP_FILE"

COLOR_DESKTOP_FILE="$HOME/.local/share/applications/statusline-color-cycle.desktop"

cat > "$COLOR_DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Statusline Color Cycle
Comment=Cycle claude-statusline color palette (next)
Exec=python3 ${CYCLE_SCRIPT} color next
Terminal=false
Type=Application
Categories=Utility;
NoDisplay=true
EOF

echo "✓ Created desktop entry: $COLOR_DESKTOP_FILE"

# Register global shortcut via kwriteconfig6
kwriteconfig6 --file "$CONFIG_FILE" \
    --group "statusline-theme-cycle.desktop" \
    --key "_launch" \
    "$SHORTCUT_KEY,none,Statusline Theme Cycle"

echo "✓ Registered shortcut: $SHORTCUT_KEY → cycle next theme"

kwriteconfig6 --file "$CONFIG_FILE" \
    --group "statusline-color-cycle.desktop" \
    --key "_launch" \
    "$COLOR_SHORTCUT_KEY,none,Statusline Color Cycle"

echo "✓ Registered shortcut: $COLOR_SHORTCUT_KEY → cycle next color"

# Reload KDE shortcuts
if command -v qdbus6 &>/dev/null; then
    qdbus6 org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.reloadConfig 2>/dev/null || true
    echo "✓ Reloaded KDE global shortcuts"
elif command -v qdbus &>/dev/null; then
    qdbus org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.reloadConfig 2>/dev/null || true
    echo "✓ Reloaded KDE global shortcuts"
else
    echo "⚠ Could not reload shortcuts automatically. Log out and back in, or run:"
    echo "  qdbus6 org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.reloadConfig"
fi

echo ""
echo "Done! Keyboard shortcuts registered:"
echo "  $SHORTCUT_KEY → cycle data themes"
echo "  $COLOR_SHORTCUT_KEY → cycle color palettes"
echo "Run 'python3 ${CYCLE_SCRIPT} list' to see all themes."
echo "Run 'python3 ${CYCLE_SCRIPT} color list' to see all palettes."
