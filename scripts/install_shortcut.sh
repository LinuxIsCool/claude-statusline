#!/usr/bin/env bash
# Install keyboard shortcuts for statusline theme/color cycling.
# Auto-detects desktop environment and delegates or prints instructions.
#
# Supported: KDE Plasma 6 (auto-install), GNOME (gsettings), Sway/Hyprland (print config)
# Idempotent — safe to re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CYCLE_SCRIPT="${SCRIPT_DIR}/cycle_theme.py"

if [ ! -f "$CYCLE_SCRIPT" ]; then
    echo "⚠ cycle_theme.py not found at: $CYCLE_SCRIPT"
    exit 1
fi

DE="${XDG_CURRENT_DESKTOP:-unknown}"

case "$DE" in
    *KDE*)
        echo "Detected KDE Plasma — delegating to install_kde_shortcut.sh"
        exec "$SCRIPT_DIR/install_kde_shortcut.sh"
        ;;
    *GNOME*)
        echo "Detected GNOME — setting up custom keybindings via gsettings"
        echo ""

        SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
        BINDING_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

        # Read existing custom keybindings
        EXISTING=$(gsettings get "$SCHEMA" custom-keybindings 2>/dev/null || echo "@as []")

        # Theme shortcut
        THEME_PATH="${BINDING_PATH}/statusline-theme/"
        gsettings set "${SCHEMA}.custom-keybinding:${THEME_PATH}" name "Statusline Theme Cycle"
        gsettings set "${SCHEMA}.custom-keybinding:${THEME_PATH}" command "python3 ${CYCLE_SCRIPT} next"
        gsettings set "${SCHEMA}.custom-keybinding:${THEME_PATH}" binding "<Ctrl><Shift>t"
        echo "✓ Registered Ctrl+Shift+T → cycle theme"

        # Color shortcut
        COLOR_PATH="${BINDING_PATH}/statusline-color/"
        gsettings set "${SCHEMA}.custom-keybinding:${COLOR_PATH}" name "Statusline Color Cycle"
        gsettings set "${SCHEMA}.custom-keybinding:${COLOR_PATH}" command "python3 ${CYCLE_SCRIPT} color next"
        gsettings set "${SCHEMA}.custom-keybinding:${COLOR_PATH}" binding "<Ctrl><Shift>c"
        echo "✓ Registered Ctrl+Shift+C → cycle color"

        # Add to keybinding list if not present
        if [[ "$EXISTING" != *"statusline-theme"* ]]; then
            # Append our paths to existing list
            NEW_LIST=$(echo "$EXISTING" | sed "s|]|, '${THEME_PATH}', '${COLOR_PATH}']|" | sed "s|@as \[\]|['${THEME_PATH}', '${COLOR_PATH}']|")
            gsettings set "$SCHEMA" custom-keybindings "$NEW_LIST"
        fi

        echo ""
        echo "Done! GNOME shortcuts registered."
        ;;
    *sway*|*Sway*|*hyprland*|*Hyprland*)
        echo "Detected $DE — add these to your config:"
        echo ""
        if [[ "$DE" == *"yprland"* ]]; then
            echo "# ~/.config/hypr/hyprland.conf"
            echo "bind = CTRL SHIFT, T, exec, python3 ${CYCLE_SCRIPT} next"
            echo "bind = CTRL SHIFT, C, exec, python3 ${CYCLE_SCRIPT} color next"
        else
            echo "# ~/.config/sway/config"
            echo "bindsym Ctrl+Shift+t exec python3 ${CYCLE_SCRIPT} next"
            echo "bindsym Ctrl+Shift+c exec python3 ${CYCLE_SCRIPT} color next"
        fi
        echo ""
        echo "Then reload your config."
        ;;
    *)
        echo "Desktop environment: ${DE}"
        echo ""
        echo "No auto-installer for this DE. Run manually:"
        echo "  python3 ${CYCLE_SCRIPT} next         # cycle data theme"
        echo "  python3 ${CYCLE_SCRIPT} color next    # cycle color palette"
        echo ""
        echo "Or bind these commands to your preferred keyboard shortcuts."
        ;;
esac
