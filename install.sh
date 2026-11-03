#!/bin/zsh
# Usage: ./install.sh            install and start the three launchd agents
#        ./install.sh uninstall  stop and remove them
cd "$(dirname "$0")" || exit 1
DEST="$HOME/Library/LaunchAgents"
LABELS=(schedule active dashboard)
OLD=(login)

unload() {
  for n in $LABELS $OLD; do
    launchctl unload "$DEST/com.megibida.emaildigest.$n.plist" 2>/dev/null
  done
}

if [[ "$1" == "uninstall" ]]; then
  unload
  for n in $LABELS $OLD; do rm -f "$DEST/com.megibida.emaildigest.$n.plist"; done
  echo "Removed."
  exit 0
fi

# Clean out the old login agent, which the "active" one replaced.
for n in $OLD; do rm -f "$DEST/com.megibida.emaildigest.$n.plist"; done

# The dashboard agent can't start if something else already owns the port.
unload
sleep 2  # give the old dashboard a moment to release the port
if lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null; then
  echo "Port 8765 is in use (probably a uvicorn running in a terminal). Stop it with Ctrl+C, then run this again."
  exit 1
fi

mkdir -p "$DEST"
for n in $LABELS; do
  cp "launchd/com.megibida.emaildigest.$n.plist" "$DEST/"
  launchctl load "$DEST/com.megibida.emaildigest.$n.plist"
done
echo "Installed. Dashboard: http://localhost:8765"
launchctl list | grep emaildigest
