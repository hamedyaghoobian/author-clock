#!/bin/sh
# One-time setup on the Jetson Nano (JetPack 4 / Ubuntu 18.04). Run from the repo:
#   ./deploy/setup-jetson.sh            # uses gemma3:1b
#   MODEL=qwen2.5:1.5b ./deploy/setup-jetson.sh
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${MODEL:-gemma3:1b}"

echo "== packages"
sudo apt-get update
sudo apt-get install -y unclutter x11-xserver-utils curl
# kiosk.sh falls back to Firefox (preinstalled on L4T) if Chromium isn't available.
sudo apt-get install -y chromium-browser || echo "chromium-browser unavailable; the kiosk will use Firefox"
# Nicer type if available; the page falls back to DejaVu Serif without them.
sudo apt-get install -y fonts-ebgaramond || true
sudo apt-get install -y fonts-ibm-plex || true

echo "== power: max performance mode (all 4 cores, 10 W)"
sudo nvpmodel -m 0 || true

echo "== model"
if command -v ollama >/dev/null; then
  ollama pull "$MODEL"
else
  echo "Ollama is not installed. Try:  curl -fsSL https://ollama.com/install.sh | sh"
  echo "If it won't run on JetPack 4, use llama.cpp instead (see README, 'Plan B')."
fi

echo "== config"
[ -f "$DIR/config.json" ] || sed "s/\"gemma3:1b\"/\"$MODEL\"/" "$DIR/config.example.json" > "$DIR/config.json"

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
echo "Done. Turn on automatic login (Settings > Users) and reboot."
echo "Check the server:  journalctl -u author-clock -f"
