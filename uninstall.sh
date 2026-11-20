#!/bin/sh
# Removes the app. Mouse backups in ~/.local/share/redragon-m917/copias are kept.
SHARE="$HOME/.local/share"
rm -f "$HOME/.local/bin/redragon-m917" "$SHARE/applications/redragon-m917.desktop" \
      "$SHARE/icons/hicolor/scalable/apps/redragon-m917-config.svg" \
      "$SHARE/redragon-m917/m917.py"
rm -rf "$SHARE/redragon-m917/res" "$SHARE/redragon-m917/__pycache__"
echo "Removed. Backups kept in $SHARE/redragon-m917/copias"
echo "To remove the udev rule: sudo rm /etc/udev/rules.d/70-redragon-m917.rules"
