#!/bin/sh
# One-time setup for the wall: a Jetson Nano (JetPack 4) or a Raspberry Pi 4/5 running
# 64-bit Raspberry Pi OS. Run from the repo:
#   ./deploy/setup.sh                               # detects the board, uses gemma3:1b
#   MODEL=qwen2.5:1.5b ./deploy/setup.sh
#   TIMEZONE=America/Chicago ./deploy/setup.sh      # default America/New_York
#   BOARD=pi ./deploy/setup.sh                      # skip detection (pi | jetson | other)
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${MODEL:-gemma3:1b}"

if [ -z "$BOARD" ]; then
  if [ -f /etc/nv_tegra_release ] || command -v nvpmodel >/dev/null 2>&1; then
    BOARD=jetson
  elif grep -qs "Raspberry Pi" /proc/device-tree/model; then
    BOARD=pi
  else
    BOARD=other
  fi
fi
echo "== board: $BOARD"

if [ "$BOARD" = pi ] && [ "$(uname -m)" != aarch64 ]; then
  echo "This Pi is running a 32-bit OS. Ollama needs 64-bit Raspberry Pi OS; reflash with"
  echo "the 64-bit image in Raspberry Pi Imager, then run this again."
  exit 1
fi

echo "== packages"
sudo apt-get update
sudo apt-get install -y unclutter x11-xserver-utils curl python3
# The browser is "chromium" on current Raspberry Pi OS and "chromium-browser" on older
# Ubuntu/L4T; kiosk.sh finds either, and falls back to Firefox.
sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser \
  || echo "Chromium unavailable; the kiosk will use Firefox"
# Nicer type if available; the page falls back to DejaVu Serif without them.
sudo apt-get install -y fonts-ebgaramond || true
sudo apt-get install -y fonts-ibm-plex || true

echo "== timezone (the clock tells local time)"
sudo timedatectl set-timezone "${TIMEZONE:-America/New_York}"

case "$BOARD" in
  jetson)
    echo "== power: max performance mode (all 4 cores, 10 W)"
    sudo nvpmodel -m 0 || true
    WATTS=10
    ;;
  pi)
    # Current Raspberry Pi OS runs Wayland; the kiosk's no-blanking and no-cursor
    # commands need X11. Also log in to the desktop automatically.
    if command -v raspi-config >/dev/null; then
      echo "== display: switch to X11, desktop autologin"
      sudo raspi-config nonint do_wayland W1 \
        || echo "Couldn't switch to X11; do it in: sudo raspi-config > Advanced Options > Wayland > X11"
      sudo raspi-config nonint do_boot_behaviour B4 \
        || echo "Couldn't set autologin; do it in: sudo raspi-config > System Options > Boot / Auto Login"
    fi
    # Rough draw while the CPU is busy writing: Pi 4 about 6 W, Pi 5 about 9 W.
    if grep -qs "Raspberry Pi 5" /proc/device-tree/model; then WATTS=9; else WATTS=6; fi
    ;;
  *)
    WATTS=10
    ;;
esac

echo "== model"
if ! command -v ollama >/dev/null && [ "$BOARD" = pi ]; then
  # Ollama supports 64-bit ARM Linux directly, so on a Pi the official installer just works.
  curl -fsSL https://ollama.com/install.sh | sh
fi
if command -v ollama >/dev/null; then
  ollama pull "$MODEL"
else
  echo "Ollama is not installed. Try:  curl -fsSL https://ollama.com/install.sh | sh"
  echo "If it won't run on JetPack 4, use llama.cpp instead (see README, 'Plan B')."
fi

echo "== config"
if [ ! -f "$DIR/config.json" ]; then
  python3 - "$DIR" "$MODEL" "$WATTS" <<'PY'
import json, sys
root, model, watts = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(root + "/config.example.json") as fh:
    cfg = json.load(fh)
cfg["model"], cfg["watts"] = model, watts
with open(root + "/config.json", "w") as fh:
    json.dump(cfg, fh, indent=2)
    fh.write("\n")
PY
fi

echo "== clock server (systemd service, runs as $USER)"
sed "s#__DIR__#$DIR#g; s#__USER__#$USER#g" "$DIR/deploy/author-clock.service" \
  | sudo tee /etc/systemd/system/author-clock.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now author-clock.service

echo "== kiosk at login"
chmod +x "$DIR/deploy/kiosk.sh"
mkdir -p "$HOME/.config/autostart"
sed "s#__DIR__#$DIR#g" "$DIR/deploy/author-clock.desktop" > "$HOME/.config/autostart/author-clock.desktop"

echo
if [ "$BOARD" = pi ]; then
  echo "Done. Reboot to start the clock:  sudo reboot"
else
  echo "Done. Turn on automatic login (Settings > Users) and reboot."
fi
echo "Check the server:  journalctl -u author-clock -f"
