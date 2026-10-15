#!/bin/sh
# Opens the Author Clock full-screen. Started at login by ~/.config/autostart/author-clock.desktop.
URL="${AUTHOR_CLOCK_URL:-http://127.0.0.1:8340/}"

# Never blank, never sleep, no cursor.
xset s off -dpms s noblank 2>/dev/null
command -v unclutter >/dev/null && unclutter -idle 0.5 -root &

# Wait for the clock server (it starts as a systemd service).
for i in $(seq 1 60); do
  curl -sf "${URL}api/now" >/dev/null && break
  sleep 2
done

# Chromium remembers crashes from hard power-offs; clear that so no restore bubble appears.
PREFS="$HOME/.config/chromium/Default/Preferences"
[ -f "$PREFS" ] && sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]*"/"exit_type":"Normal"/' "$PREFS"

BROWSER=$(command -v chromium-browser || command -v chromium)
if [ -z "$BROWSER" ]; then
  exec firefox --kiosk "$URL"
fi
exec "$BROWSER" \
  --kiosk --incognito \
  --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --disable-translate --no-first-run --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  "$URL"
