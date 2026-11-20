#!/bin/sh
# Installs the Redragon M917 app for the current user.
# The udev rule (needed to talk to the mouse without root) is installed with sudo/pkexec.
set -e
cd "$(dirname "$0")"
BIN="$HOME/.local/bin"
SHARE="$HOME/.local/share"

echo "-> app"
mkdir -p "$SHARE/redragon-m917/res" "$BIN" "$SHARE/applications" "$SHARE/icons/hicolor/scalable/apps"
install -m644 app/m917.py "$SHARE/redragon-m917/m917.py"
install -m644 app/res/*.png "$SHARE/redragon-m917/res/"
install -m644 app/res/redragon-m917-config.svg "$SHARE/icons/hicolor/scalable/apps/"
printf '#!/bin/sh\nexec /usr/bin/python3 -I "%s/redragon-m917/m917.py" "$@"\n' "$SHARE" > "$BIN/redragon-m917"
chmod +x "$BIN/redragon-m917"
sed "s|@BIN@|$BIN|" app/redragon-m917.desktop > "$SHARE/applications/redragon-m917.desktop"

echo "-> udev rule (asks for your password)"
if [ ! -f /etc/udev/rules.d/70-redragon-m917.rules ] || ! cmp -s udev/70-redragon-m917.rules /etc/udev/rules.d/70-redragon-m917.rules; then
    SUDO=sudo; command -v sudo >/dev/null || SUDO=pkexec
    $SUDO sh -c "install -m644 '$PWD/udev/70-redragon-m917.rules' /etc/udev/rules.d/ && udevadm control --reload && udevadm trigger --subsystem-match=hidraw --action=change"
fi

echo
echo "Done. Open 'Redragon M917' from the app menu."
