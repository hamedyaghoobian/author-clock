#!/usr/bin/env python3
"""Author Clock: a wall clock that writes one sentence per minute with a local language model.

The server does two jobs:
  * a background "author" thread asks the model for the NEXT minute's sentence while the
    current one is on screen, so the display never waits on generation (which takes
    10-30 s on a Jetson Nano's CPU);
  * a tiny HTTP server hands the page in static/ the current sentence as JSON.

Standard library only, Python 3.6+, so it runs on a stock Jetson Nano (JetPack 4).
"""
import copy
import json
import os
import random
import re
import socketserver
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib import request as urlrequest
from urllib.parse import parse_qs, urlparse

import timewords

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8340,
    # "ollama" talks to Ollama's /api/chat. "openai" talks to any OpenAI-compatible
    # /v1/chat/completions server, e.g. llama.cpp's llama-server.
    "backend": "ollama",
    "backend_url": "http://127.0.0.1:11434",
    "model": "gemma3:1b",
    "temperature": 0.9,
    "max_tokens": 70,
    "keep_alive": "24h",  # keep the model loaded between minutes; reloading is slow on a Nano
    "request_timeout": 75,
    "think": None,  # set false for reasoning models (qwen3 etc.) so they answer directly
    "place": "the lab",
    "machine": "a Jetson Nano with four gigabytes of memory and a small fan",
    "archive_dir": "archive",
    "night_hours": [23, 7],  # the display dims between these hours
    "accent": "#ff6a2b",
    "voices": [
        {
            "id": "field-notes",
            "label": "Field notes",
            "instruction": "You are an anthropologist quietly taking field notes in {place}. "
                           "Describe one small, concrete thing happening at this minute.",
        },
        {
            "id": "dispatch-2126",
            "label": "Dispatch from 2126",
            "instruction": "You are a historian in the year 2126 describing this exact minute in "
                           "{place} from old records. Be specific and a little wistful.",
        },
        {
            "id": "machine-diary",
            "label": "Machine diary",
            "instruction": "You are the computer running this clock: {machine}. Your processor is "
                           "at {temp}. Write a diary line about this minute from your point of view.",
        },
        {
            "id": "forecast",
            "label": "Temporal forecast",
            "instruction": "You are a weather forecaster who forecasts the mood of time instead of "
                           "the weather. Give the outlook for {place}.",
        },
        {
            "id": "oracle",
            "label": "Unreliable oracle",
            "instruction": "You are a slightly unreliable oracle. Predict, with total confidence, "
                           "something oddly specific that will happen in {place} in the next minute.",
        },
        {
            "id": "regional-manager",
            "label": "Regional manager",
            "instruction": "You are Michael Scott making an announcement to {place}: overconfident, "
                           "awkward, accidentally heartfelt.",
        },
    ],
}

# Lines the clock falls back on when the model is unreachable. Each continues "At <time>,".
NOTEBOOK = [
    "the room hums at a frequency only the radiators understand.",
    "someone in the corner is about to have the idea of the week.",
    "the clock is thinking without its model, the way you think without coffee.",
    "a cursor blinks on a screen nobody is looking at.",
    "the light through the window has moved exactly one minute's worth.",
    "an unsaved document holds its breath.",
    "the kettle in the next room considers its options.",
    "a student pretends to read and actually does.",
    "the wifi router blinks a message no one will ever decode.",
    "time becomes visible in the space between two keystrokes.",
    "this sentence was written by a person, long before you read it.",
    "somewhere a build finishes and nobody notices.",
]

_print_lock = threading.Lock()


def log(*parts):
    with _print_lock:
        print(datetime.now().strftime("%H:%M:%S"), *parts, flush=True)


def load_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    path = os.environ.get("AUTHOR_CLOCK_CONFIG", os.path.join(ROOT, "config.json"))
    if os.path.exists(path):
        with open(path) as fh:
            cfg.update(json.load(fh))
        log("config:", path)
    for key, env in (("model", "AUTHOR_CLOCK_MODEL"), ("backend", "AUTHOR_CLOCK_BACKEND"),
                     ("backend_url", "AUTHOR_CLOCK_BACKEND_URL"), ("port", "AUTHOR_CLOCK_PORT")):
        if os.environ.get(env):
            cfg[key] = int(os.environ[env]) if key == "port" else os.environ[env]
    if not os.path.isabs(cfg["archive_dir"]):
        cfg["archive_dir"] = os.path.join(ROOT, cfg["archive_dir"])
    return cfg


def soc_temperature():
    """Hottest thermal zone in degrees C, or None off-Jetson."""
    temps = []
    base = "/sys/class/thermal"
    try:
        for zone in os.listdir(base):
            try:
                with open(os.path.join(base, zone, "temp")) as fh:
                    value = int(fh.read().strip()) / 1000.0
                if 0 < value < 120:
                    temps.append(value)
            except (OSError, ValueError):
                continue
    except OSError:
        return None
    return round(max(temps), 1) if temps else None


def minute_key(moment):
    return moment.strftime("%Y-%m-%dT%H:%M")


def voice_for(cfg, moment):
    voices = cfg["voices"]
    # A fixed voice per minute: the same minute always gets the same voice, and the
    # sequence walks through all voices before repeating.
    return voices[(moment.hour * 60 + moment.minute) % len(voices)]


# ---------------------------------------------------------------------------- the model

def build_messages(cfg, voice, lead, moment, temp_c):
    temp = "{:.0f} degrees Celsius".format(temp_c) if temp_c is not None else "a comfortable temperature"
    instruction = voice["instruction"].format(place=cfg["place"], machine=cfg["machine"], temp=temp)
    system = (
        "You write a single sentence for a clock on the wall of {place}. {instruction} "
        "You will be given the first words of the sentence. Reply with only the rest of it: "
        "no quotation marks, no preamble, no emoji, no clock times or numbers, under 35 words."
    ).format(place=cfg["place"], instruction=instruction)
    user = "Today is {day}, {month} {date}.\nSentence so far: {lead}\nRest of the sentence:".format(
        day=moment.strftime("%A"), month=moment.strftime("%B"), date=moment.day, lead=lead)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _post_stream(url, payload, timeout):
    req = urlrequest.Request(url, data=json.dumps(payload).encode("utf-8"),
                             headers={"Content-Type": "application/json"})
    return urlrequest.urlopen(req, timeout=timeout)


def generate_ollama(cfg, messages):
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": True,
        "keep_alive": cfg["keep_alive"],
        "options": {"temperature": cfg["temperature"], "num_predict": cfg["max_tokens"]},
    }
    if cfg.get("think") is not None:
        payload["think"] = cfg["think"]
    text, stats, first = [], {}, None
    with _post_stream(cfg["backend_url"].rstrip("/") + "/api/chat", payload, cfg["request_timeout"]) as resp:
        for raw in resp:
            if not raw.strip():
                continue
            chunk = json.loads(raw.decode("utf-8"))
            if chunk.get("error"):
                raise RuntimeError(chunk["error"])
            piece = chunk.get("message", {}).get("content", "")
            if piece:
                if first is None:
                    first = time.time()
                text.append(piece)
            if chunk.get("done"):
                stats = chunk
    eval_count = stats.get("eval_count")
    eval_seconds = (stats.get("eval_duration") or 0) / 1e9
    return "".join(text), {
        "tokens": eval_count,
        "tokens_per_second": round(eval_count / eval_seconds, 1) if eval_count and eval_seconds else None,
        "first_token_at": first,
    }


def generate_openai(cfg, messages):
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": True,
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
    }
    text, first, pieces = [], None, 0
    url = cfg["backend_url"].rstrip("/") + "/v1/chat/completions"
    with _post_stream(url, payload, cfg["request_timeout"]) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            delta = json.loads(data)["choices"][0].get("delta", {}).get("content") or ""
            if delta:
                if first is None:
                    first = time.time()
                pieces += 1
                text.append(delta)
    seconds = time.time() - first if first else 0
    return "".join(text), {
        "tokens": pieces,
        "tokens_per_second": round(pieces / seconds, 1) if pieces and seconds else None,
        "first_token_at": first,
    }


def clean_continuation(text, lead):
    """Coax a small model's reply into the tail of a sentence that starts with `lead`."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"[*_`#]+", "", text)
    text = text.strip().strip('"“”\'').strip()
    # Models often repeat the opening words despite instructions.
    if text.lower().startswith(lead.lower()):
        text = text[len(lead):]
    else:
        text = re.sub(r"^at [^,]{3,80}?,\s*", "", text, flags=re.I)
    text = text.lstrip(" ,;:-—").strip()
    text = re.sub(r"\s+", " ", text)
    # Keep at most two sentences and 45 words.
    sentences = re.findall(r"[^.!?]+[.!?]+[\"'”]?", text)
    if sentences:
        text = " ".join(s.strip() for s in sentences[:2])
    words = text.split(" ")
    if len(words) > 45:
        text = " ".join(words[:45]).rstrip(",;:") + "…"
    if text and text[-1] not in ".!?…\"'”":
        text += "."
    # It continues after a comma, so drop a capital unless it's "I" or a name-ish word.
    first = text.split(" ", 1)[0].rstrip(".,!?…;:") if text else ""
    if first and first[0].isupper() and (first == "A" or first != first.upper()) and (first.lower() in {
            "the", "a", "an", "someone", "somewhere", "everyone", "nobody", "my", "our",
            "this", "that", "it", "we", "you", "they", "there", "time", "today", "here",
            "well", "oh", "so", "okay", "alright", "listen", "and", "but", "as", "while",
            "outside", "inside", "somebody", "every", "all", "no", "one"}
            or first.lower().endswith(("ing", "ly"))):
        text = text[0].lower() + text[1:]
    return text.strip(" \"'“”")


# ---------------------------------------------------------------------------- the author

class Author(threading.Thread):
    """Keeps the sentence for the current and the next minute ready."""

    def __init__(self, cfg):
        threading.Thread.__init__(self, daemon=True)
        self.cfg = cfg
        self.entries = {}
        self.lock = threading.Lock()
        self.backoff_until = 0
        self.last_error = None
        self.status = "starting"

    def get(self, key):
        with self.lock:
            return self.entries.get(key)

    def put(self, entry):
        with self.lock:
            self.entries[entry["key"]] = entry
            cutoff = minute_key(datetime.now() - timedelta(minutes=10))
            for key in [k for k in self.entries if k < cutoff]:
                del self.entries[key]
        self.archive(entry)

    def archive(self, entry):
        try:
            os.makedirs(self.cfg["archive_dir"], exist_ok=True)
            path = os.path.join(self.cfg["archive_dir"], entry["key"][:10] + ".jsonl")
            with open(path, "a") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError as exc:
            log("archive failed:", exc)

    def skeleton(self, moment):
        lead, phrase = timewords.lead(moment.hour, moment.minute)
        voice = voice_for(self.cfg, moment)
        return {
            "key": minute_key(moment),
            "lead": lead,
            "phrase": phrase,
            "text": "",
            "voice": voice["label"],
            "model": self.cfg["model"],
            "source": "pending",
        }

    def from_notebook(self, moment, reason):
        entry = self.skeleton(moment)
        rng = random.Random(entry["key"])
        entry.update(text=rng.choice(NOTEBOOK), source="notebook", voice="The notebook", reason=reason)
        return entry

    def compose(self, moment):
        entry = self.skeleton(moment)
        if time.time() < self.backoff_until:
            return self.from_notebook(moment, self.last_error or "model unavailable")
        voice = voice_for(self.cfg, moment)
        temp_c = soc_temperature()
        messages = build_messages(self.cfg, voice, entry["lead"], moment, temp_c)
        generate = generate_openai if self.cfg["backend"] == "openai" else generate_ollama
        started = time.time()
        try:
            raw, stats = generate(self.cfg, messages)
            text = clean_continuation(raw, entry["lead"])
            if len(text.split()) < 3:
                raise ValueError("reply too short: {!r}".format(raw))
        except Exception as exc:  # anything at all -> the notebook; the clock must keep going
            reason = getattr(exc, "reason", None) or exc
            self.last_error = str(reason)
            self.status = "offline"
            self.backoff_until = time.time() + 30
            log("model failed:", self.last_error)
            return self.from_notebook(moment, self.last_error)
        elapsed = time.time() - started
        stats.pop("first_token_at", None)
        tps = stats.get("tokens_per_second")
        self.status = "online"
        self.last_error = None
        entry.update(stats)
        entry.update(
            text=text,
            raw=raw,
            source="model",
            seconds=round(elapsed, 1),
            # How fast the words actually arrived, so the page can replay them at that pace.
            chars_per_second=round(tps * len(raw) / stats["tokens"], 1) if tps and stats.get("tokens") else None,
            temperature=self.cfg["temperature"],
            soc_temp=temp_c,
            written_at=datetime.now().isoformat(timespec="seconds"),
        )
        log("{} [{}] {:.1f}s  {} {}".format(entry["key"], voice["id"], elapsed, entry["lead"], text))
        return entry

    def run(self):
        while True:
            try:
                self.step()
            except Exception as exc:  # never let the author thread die on a wall-mounted box
                log("author error:", repr(exc))
                time.sleep(5)

    def step(self):
        """Fill whichever of this minute / next minute is missing, else idle briefly."""
        now = datetime.now()
        current = now.replace(second=0, microsecond=0)
        upcoming = current + timedelta(minutes=1)
        if not self.get(minute_key(current)):
            # Only write for the current minute if there's time to read the result.
            if 60 - now.second > 25:
                self.put(self.compose(current))
            else:
                self.put(self.from_notebook(current, "warming up"))
            return
        if not self.get(minute_key(upcoming)):
            self.put(self.compose(upcoming))
            return
        time.sleep(0.5)


# ---------------------------------------------------------------------------- the server

CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript",
                 ".svg": "image/svg+xml", ".woff2": "font/woff2", ".png": "image/png", ".ico": "image/x-icon"}


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(cfg, author):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # silence the access log
            pass

        def send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/api/now":
                return self.api_now()
            if url.path == "/api/book":
                return self.api_book(parse_qs(url.query))
            return self.static(url.path)

        def api_now(self):
            now = datetime.now()
            current = now.replace(second=0, microsecond=0)
            entry = author.get(minute_key(current)) or author.skeleton(current)
            self.send_json({
                "now": time.time(),
                "local": now.isoformat(timespec="seconds"),
                "minute_of_day": now.hour * 60 + now.minute,
                "entry": entry,
                "next_ready": author.get(minute_key(current + timedelta(minutes=1))) is not None,
                "status": author.status,
                "error": author.last_error,
                "model": cfg["model"],
                "soc_temp": soc_temperature(),
                "night": in_night(cfg, now.hour),
                "accent": cfg["accent"],
            })

        def api_book(self, query):
            date = (query.get("date") or [datetime.now().strftime("%Y-%m-%d")])[0]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                return self.send_json({"error": "bad date"}, 400)
            path = os.path.join(cfg["archive_dir"], date + ".jsonl")
            entries = {}
            if os.path.exists(path):
                with open(path) as fh:
                    for line in fh:
                        try:
                            entry = json.loads(line)
                        except ValueError:
                            continue
                        # A minute may be written twice (notebook, then model); keep the best.
                        old = entries.get(entry["key"])
                        if not old or old.get("source") != "model":
                            entries[entry["key"]] = entry
            self.send_json({"date": date, "entries": [entries[k] for k in sorted(entries)]})

        def static(self, path):
            if path in ("", "/"):
                path = "/index.html"
            full = os.path.realpath(os.path.join(STATIC_DIR, path.lstrip("/")))
            if not full.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(full):
                self.send_error(404)
                return
            with open(full, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def in_night(cfg, hour):
    start, end = cfg.get("night_hours") or (None, None)
    if start is None:
        return False
    return hour >= start or hour < end if start > end else start <= hour < end


def main():
    cfg = load_config()
    log("model {} via {} at {}".format(cfg["model"], cfg["backend"], cfg["backend_url"]))
    author = Author(cfg)
    author.start()
    server = ThreadingHTTPServer((cfg["host"], cfg["port"]), make_handler(cfg, author))
    log("serving http://{}:{}/".format(cfg["host"], cfg["port"]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
