#!/bin/bash
# sync-rofi-theme.sh — link the rofi variant to match the current hyprtk-bar theme
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
#
# The bar's ``theme.source`` selects the rofi variant:
#   pywal    -> hyprtk-pywal (the dynamic pywal variant; re-tints on wallpaper change)
#   imported -> the matching imported-theme variant (e.g. hyprtk-aero -> hyprtk-aero.rasi)
#   manual   -> hyprtk (default glass)
# Missing variants fall back to hyprtk.

bar_config="$HOME/.config/hyprtk-bar/config.json"
variant_dir="$SCRIPT_DIR/rofi/variants"
[ -d "$variant_dir" ] || variant_dir="$HOME/hyprtk/configs/rofi/variants"
symlink="$HOME/.config/rofi/variant.rasi"
[ -d "$(dirname "$symlink")" ] || symlink="$HOME/hyprtk/configs/rofi/variant.rasi"

theme="hyprtk"

if [ -f "$bar_config" ]; then
    source=$(python3 -c "import json;d=json.load(open('$bar_config'));print(d.get('theme',{}).get('source',''))" 2>/dev/null)
    theme_name=$(python3 -c "import json;d=json.load(open('$bar_config'));print(d.get('theme',{}).get('theme_name',''))" 2>/dev/null)
    if [ "$source" = "pywal" ]; then
        theme="hyprtk-pywal"
    elif [ -n "$theme_name" ]; then
        theme="$theme_name"
    fi
fi

theme="${theme%-top}"
theme="${theme%-bottom}"

if [ -f "$variant_dir/$theme.rasi" ]; then
    ln -sf "$variant_dir/$theme.rasi" "$symlink"
else
    ln -sf "$variant_dir/hyprtk.rasi" "$symlink"
fi
