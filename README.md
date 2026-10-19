# Author Clock

A wall clock that doesn't show the time. It writes it.

Every minute, a small language model running on a Jetson Nano or a Raspberry Pi on the wall of the computer science lab writes one sentence that starts with the time, *"At quarter past two in the afternoon, …"*. Each sentence is on screen for sixty seconds and is never shown again.

It knows what's happening outside the window. From the lab's coordinates (Allentown, PA by default) it works out where the sun is (dawn, golden hour, dusk, night) with no internet, and it fetches the current weather from [Open-Meteo](https://open-meteo.com/) (free, no API key). Those observations go into the prompt, so a sentence at dusk in the rain reads differently from one on a bright morning.

The display doesn't hide how it works:

- **Top rail:** what the clock perceived for this sentence ("outside: dusk · light rain · 12 °C"), the minute of the day (№ 0847 / 1440), and the time.
- **Bottom rail:** which model wrote the line, how many tokens it took, how fast they came, and how many seconds before its minute the sentence was written.
- **The sentence** types in at roughly the pace the model produced it. A hairline sweeps across each minute, and a ribbon along the bottom fills as the day passes.

Four things make it more than a clock:

- **Confidence as type.** Each word is drawn as solid as the model was sure of it. Where the model was guessing, words go faint and shake slightly, so you can see where the machine was unsure.
- **Decay.** "This sentence exists for one minute" is something you watch. From about 24 s in, the letters erode to a ghost, least-certain words first.
- **Talk back.** A QR code in the corner opens a page on the lab network where anyone can give the clock one word. The clock has to write it into one of its next sentences, underlined in the accent colour, and the page tells you when to look up. A blocklist and a one-word-a-minute limit keep the wall kind.
- **The midnight ritual.** At 23:59:12 the day's sentences stream past, then the whole day appears at once as a wall of tiny type with a tally: sentences, words, tokens, time spent thinking, and roughly how much electricity it took. Then everything clears, the clock forgets, and at 00:00 "At midnight," starts a new day.

Every sentence is saved, so the clock writes a 1,440-sentence book each day; `/book.html` shows it.

## How it works

```
clock_server.py   ── background "author" thread ──►  Ollama (or llama.cpp)
   │                writes the NEXT minute's line        gemma3:1b on CPU
   │                while this one is showing
   ├─ senses.py  → sun position (offline) + weather (Open-Meteo)
   ├─ talkback.py→ word filter + queue for the /say page (blocklist.txt)
   ├─ /api/now   → the current sentence + stats (JSON)
   ├─ /say       → the talk-back page phones open from the QR code
   ├─ /api/book  → every sentence from a given day
   └─ static/    → the wall display (index.html) and the day's book (book.html)
        ▲
   Chromium in kiosk mode on the board's screen
```

- **No dependencies.** Standard library only, Python 3.6+, so it runs on the Nano's stock JetPack 4 Python and on Raspberry Pi OS. Nothing to `pip install`.
- **Never stalls.** A 1B model on a small board's CPU takes roughly 10–30 s per sentence, so the server writes each minute's line during the minute before. If the model is down or slow, the clock falls back to a hand-written notebook of lines and keeps going.
- **Grounded in observations.** Sun and weather arrive as plain facts in the prompt ("The sun has just set; dusk is settling outside the window."). A 1B model still slips in rain on a clear day or a setting sun at 2 pm, so each observation lists words it rules out, and the clock asks once more when a sentence uses one. In testing, about 1 sentence in 24 still gets through.
- **Remembers without copying.** Showing a 1B model its earlier sentences makes it copy them: in testing, 9 of 12 came out as near-repeats. So memory steers instead. Each minute the clock picks something in the room it hasn't mentioned lately (the whiteboard, a 3D printer, a forgotten jacket) and nudges the model towards it. If a sentence still mostly repeats an earlier one, the clock asks once more. In testing that gave 12 different sentences out of 12.
- **Confidence comes from the model itself.** Ollama (and llama.cpp) can report the probability of each token. The page uses the least likely token in each word. Older backends that don't report it just get plain type.
- **The time is always right.** The model only writes what comes after the comma. The clock sets the opening words itself, so the model can't get the time wrong or paraphrase it away. If the server stops, the page keeps showing the correct time words on its own instead of freezing on an old minute.

## Run it on a laptop

```bash
ollama pull gemma3:1b
```

```bash
python3 clock_server.py
```

Open http://127.0.0.1:8340 for the clock, http://127.0.0.1:8340/say for the talk-back page, and http://127.0.0.1:8340/book.html for today's book. To rehearse the midnight ritual at any time, open http://127.0.0.1:8340/?ritual=1.

The server listens on the lab network (`0.0.0.0`) so phones can reach `/say`. Set `"host": "127.0.0.1"` in `config.json` to keep it local, or `"talk_back": false` to turn talk-back off.

## Put it on the wall

It runs on an original **Jetson Nano** (4 GB, JetPack 4) or a **Raspberry Pi 4 or 5** with 4 GB or more. On both, the model runs on the CPU (Ollama doesn't use the Nano's GPU on JetPack 4). The Pi's newer CPU cores are faster, and current Raspberry Pi OS makes the setup easier. Neither board has been timed yet.

The same two commands set up either board:

```bash
git clone https://github.com/hamedyaghoobian/author-clock.git
```

```bash
cd author-clock && ./deploy/setup.sh
```

[deploy/setup.sh](deploy/setup.sh) detects the board (or set `BOARD=pi` / `BOARD=jetson`), then:

- installs Chromium (falling back to Firefox) and fonts
- sets the timezone to `America/New_York` (override with `TIMEZONE=...`)
- pulls the model (override with `MODEL=...`)
- creates `config.json` from `config.example.json`, with Allentown's coordinates and the board's power draw for the midnight tally already filled in
- installs the server as a systemd service and adds a kiosk autostart entry ([deploy/kiosk.sh](deploy/kiosk.sh): no screen blanking, no cursor, no crash bubbles)

### On a Jetson Nano

The script also puts the Nano in max-performance mode (10 W). Afterwards, turn on automatic login (Settings > Users) and reboot. If Ollama won't install on JetPack 4, see Plan B below.

### On a Raspberry Pi

- **Use 64-bit Raspberry Pi OS** (with desktop). Ollama only runs on 64-bit ARM; the script stops with a message on a 32-bit system.
- The script installs Ollama with its official installer.
- Current Raspberry Pi OS uses Wayland, but the kiosk's no-blanking and hidden-cursor settings need X11. So the script switches the Pi to X11 and turns on desktop autologin through `raspi-config`. If either step fails, it tells you where to do it by hand.
- Reboot when it's done: `sudo reboot`.
- **Keep it cool.** Writing a sentence every minute keeps the CPU busy, and a Pi 4 without a heatsink or fan slows down when it gets hot. The top rail shows the chip temperature. A small case fan is worth it.

Tips for 4 GB boards:

- Run the desktop with as little else open as possible. The model and Chromium share the 4 GB (with the GPU on the Nano), so there isn't much headroom. A 1B model at 4-bit takes about 1 GB.
- Set `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_NUM_PARALLEL=1` for the Ollama service. The server already asks Ollama to keep the model loaded between minutes (`keep_alive`), because reloading it every minute would be too slow.
- If Chromium flickers, add `--disable-gpu` to the flags in `kiosk.sh`.

### Plan B: llama.cpp instead of Ollama

This is only needed on the Jetson Nano: recent Ollama builds may not run on Ubuntu 18.04 / JetPack 4. The server also speaks the OpenAI-compatible API, so you can build [llama.cpp](https://github.com/ggml-org/llama.cpp) on the Nano (CPU build; Ubuntu 18.04 needs `gcc-8`/`g++-8` and a newer CMake), download a `gemma-3-1b-it` Q4 GGUF, and run:

```bash
./build/bin/llama-server -m gemma-3-1b-it-Q4_K_M.gguf --port 8080 -c 1024
```

Then set this in `config.json`:

```json
{ "backend": "openai", "backend_url": "http://127.0.0.1:8080" }
```

## Make it yours

Edit `config.json` (the setup script creates it; on a laptop, copy `config.example.json`). Every key in `DEFAULT_CONFIG` at the top of [clock_server.py](clock_server.py) can be overridden there:

| key | what it does |
| --- | --- |
| `model` | Any Ollama model tag. `gemma3:1b` is the default; `qwen2.5:1.5b` and `llama3.2:1b` also fit on a 4 GB board. For a reasoning model (e.g. qwen3), also set `"think": false`. |
| `latitude`, `longitude` | Where the lab is (Allentown, PA in the example config). The sun and weather senses stay off when these are `null`. |
| `weather` | `false` to skip Open-Meteo, e.g. if the board has no internet. Sun position still works offline. |
| `place` | What the clock calls the room (default "the computer science lab"). |
| `prompt` | What the model is asked to write. `{place}` is filled in. |
| `things` | Things in the room the clock wanders between, one per minute. Fill it with what's actually in your lab. |
| `talk_back` | `false` turns off the QR code and the `/say` page. |
| `public_url` | The address the QR code points to, if the auto-detected one is wrong (e.g. `"http://authorclock.local:8340"`). |
| `blocklist` | Path to the word blocklist (default [blocklist.txt](blocklist.txt)). |
| `watts` | The board's power draw while thinking, for the midnight tally. Setup writes 10 for a Nano, 6 for a Pi 4, 9 for a Pi 5. |
| `temperature` | Higher means stranger sentences. |
| `night_hours` | The display dims between these hours. |
| `accent` | The highlight colour. |

The env vars `AUTHOR_CLOCK_MODEL`, `AUTHOR_CLOCK_BACKEND_URL` and `AUTHOR_CLOCK_PORT` override the config file.

## Ideas for students

- **More senses** ([senses.py](senses.py) shows the pattern: return a short label and a plain fact). Next candidates: the class schedule, the clock's own recent sentences, a USB webcam for light, motion and occupancy, a mic level, a door counter, or the room's CO₂.
- **The book.** Print a day's sentences as a zine. Compare a Tuesday with a Saturday. Track how often the model mentions coffee.
- **Two clocks arguing.** A second board that replies to the first one's sentence.
- **Model swap day.** Run a different model each week and label it on the rail. Students vote on which one "writes time" best.

## Where it could go next

Directions for making it more speculative, not built yet:

- **The roads not taken.** Briefly show the words that almost went in a word's place ("a student / a server / a ghost adjusts…"), and state on the rail that the model's knowledge stops years before the minute it's describing.
- **The parallel lab.** Each midnight, pick an alternate premise ("the timeline where computers run on light") and describe this lab, at this time and in this weather, in that world all day. The daily book becomes a novella.
- **The archive from 2126.** Write each sentence as a record a future historian recovered about this minute, with a catalogue number, a confidence score and the odd illegible word.

## Repo

- `clock_server.py`, `timewords.py`, `senses.py`, `talkback.py`, `blocklist.txt`, `static/`, `deploy/` — the current clock
- `static/vendor/qrcode.js` — [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) by Kazuhiko Arase (MIT), vendored so the QR code works offline
- `poetic_clock.py`, `jetson_display_clock.py` — the original Tkinter versions (need `pip install -r requirements.txt`), kept for reference

## License

MIT
