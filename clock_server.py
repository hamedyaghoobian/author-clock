#!/usr/bin/env python3
"""Author Clock: a wall clock that writes one sentence per minute with a local language model.

The server does two jobs:
  * a background "author" thread asks the model for the NEXT minute's sentence while the
    current one is on screen, so the display never waits on generation (which takes
    10-30 s on a Jetson Nano's CPU);
  * a tiny HTTP server hands the page in static/ the current sentence as JSON, and takes
    words from people in the lab (talk-back, see talkback.py).

Standard library only, Python 3.6+, so it runs on a stock Jetson Nano (JetPack 4).
"""
import collections
import copy
import math
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

import senses
import talkback
import timewords

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")

DEFAULT_CONFIG = {
    "host": "0.0.0.0",  # reachable on the lab network, for the talk-back page
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
    "place": "the computer science lab",
    # Where the lab is, for sunrise/sunset and weather. Both senses stay off until set.
    "latitude": None,
    "longitude": None,
    "weather": True,  # current conditions from Open-Meteo (needs internet, no API key)
    "archive_dir": "archive",
    "night_hours": [23, 7],  # the display dims between these hours
    "accent": "#ff6a2b",
    "talk_back": True,  # QR code + /say page where people give the clock a word
    "public_url": None,  # e.g. "http://authorclock.local:8340" if the auto-detected address is wrong
    # Things in the room. Each minute the clock picks one it hasn't written about lately and
    # nudges the model toward it, so the day's sentences wander around the lab. (Showing a
    # 1B model its earlier sentences makes it copy them, so memory steers instead.)
    "things": [
        "the whiteboard", "a half-erased diagram", "a tangle of cables", "the server rack",
        "a 3D printer", "a sticky note on a monitor", "a stack of library books", "a backpack",
        "a cold cup of coffee", "the fluorescent lights", "a terminal window", "a soldering iron",
        "a Raspberry Pi", "the door", "an empty chair", "headphones", "a laptop's fan",
        "a compiler error", "a printer", "the window", "a professor", "two students arguing",
        "a keyboard", "a robot arm", "the recycling bin", "a forgotten jacket", "an Arduino",
        "a whiteboard marker", "a phone face down on a desk", "the radiator",
    ],
    "watts": 10,  # the Nano's power while thinking, for the midnight tally (10 W mode)
    # What the model is asked to write; {place} is filled in.
    "prompt": "Write about something happening in {place} right now, coloured by what is happening outside.",
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


# ---------------------------------------------------------------------------- the model

def build_messages(cfg, lead, moment, observations, thing=None, offering=None):
    system = (
        "You write a single sentence for a clock on the wall of {place}. {prompt} "
        "Stay true to the observations you are given; never contradict them. "
        "You will be given the first words of the sentence. Reply with only the rest of it: "
        "no quotation marks, no preamble, no emoji, no clock times or numbers, under 35 words."
    ).format(place=cfg["place"], prompt=cfg["prompt"].format(place=cfg["place"]))
    lines = ["Today is {}, {} {}.".format(moment.strftime("%A"), moment.strftime("%B"), moment.day)]
    lines += [o["fact"] for o in observations]
    if offering:
        lines.append('Someone in the lab has given you the word "{}". Use it in the sentence.'.format(offering))
    elif thing:
        lines.append("Something in the room to notice: {}.".format(thing))
    user = "Observations:\n{}\nSentence so far: {}\nRest of the sentence:".format(
        "\n".join("- " + line for line in lines), lead)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _post_stream(url, payload, timeout):
    req = urlrequest.Request(url, data=json.dumps(payload).encode("utf-8"),
                             headers={"Content-Type": "application/json"})
    return urlrequest.urlopen(req, timeout=timeout)


def _token_probs(items):
    """[(token, probability)] from a backend's logprobs list; anything odd is skipped, since
    confidence is decoration and must never cost a sentence."""
    out = []
    for lp in items if isinstance(items, list) else []:
        try:
            out.append((str(lp["token"]), math.exp(float(lp["logprob"]))))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return out


def generate_ollama(cfg, messages):
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": True,
        "keep_alive": cfg["keep_alive"],
        "options": {"temperature": cfg["temperature"], "num_predict": cfg["max_tokens"]},
        "logprobs": True,  # older Ollama ignores this; the page then shows plain type
    }
    if cfg.get("think") is not None:
        payload["think"] = cfg["think"]
    text, stats, first, probs = [], {}, None, []
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
            probs.extend(_token_probs(chunk.get("logprobs")))
            if chunk.get("done"):
                stats = chunk
    eval_count = stats.get("eval_count")
    eval_seconds = (stats.get("eval_duration") or 0) / 1e9
    return "".join(text), {
        "tokens": eval_count,
        "tokens_per_second": round(eval_count / eval_seconds, 1) if eval_count and eval_seconds else None,
        "first_token_at": first,
        "token_probs": probs,
    }


def generate_openai(cfg, messages):
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": True,
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
        "logprobs": True,
    }
    text, first, pieces, probs = [], None, 0, []
    url = cfg["backend_url"].rstrip("/") + "/v1/chat/completions"
    with _post_stream(url, payload, cfg["request_timeout"]) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            choice = json.loads(data)["choices"][0]
            delta = choice.get("delta", {}).get("content") or ""
            probs.extend(_token_probs((choice.get("logprobs") or {}).get("content")))
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
        "token_probs": probs,
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
            "outside", "inside", "somebody", "every", "all", "no", "one",
            "rain", "snow", "sunlight", "light", "darkness", "dusk", "dawn", "fog", "wind"}
            or first.lower().endswith(("ing", "ly"))):
        text = text[0].lower() + text[1:]
    return text.strip(" \"'“”")


def word_confidences(text, token_probs):
    """How sure the model was of each word in `text` (split on spaces): the probability of
    the least likely token inside it, or None where a word can't be matched."""
    if not token_probs:
        return None
    produced = "".join(tok for tok, _ in token_probs)
    char_probs = []
    for tok, prob in token_probs:
        char_probs.extend([prob] * len(tok))
    lower, pos, out = produced.lower(), 0, []
    for word in text.split(" "):
        core = re.sub(r"^[^\w]+|[^\w]+$", "", word).lower()
        at = lower.find(core, pos) if core else -1
        if at < 0:
            out.append(None)
            continue
        out.append(round(min(char_probs[at:at + len(core)]), 3))
        pos = at + len(core)
    return out


STOPWORDS = set("""a an the of in on at to and or but with as by for from into onto over under
its it is are was were be been his her their they them this that these those there here
while through across against up down out off one single some""".split())


def content_words(text):
    return {w for w in re.findall(r"[a-z']+", text.lower()) if w not in STOPWORDS and len(w) > 2}


def repeats(text, earlier):
    """The earlier sentence `text` mostly re-says (half its content words or more), or None."""
    mine = content_words(text)
    for line in earlier:
        theirs = content_words(line)
        if mine and theirs and len(mine & theirs) / float(min(len(mine), len(theirs))) >= 0.5:
            return line
    return None


def contradiction(text, observations):
    """The first word in `text` that an observation rules out (rain on a dry day), or None."""
    for observation in observations:
        pattern = observation.get("contradicts")
        match = pattern and re.search(pattern, text, re.I)
        if match:
            return match.group(0)
    return None


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
        self.senses = senses.Senses(cfg)
        self.offerings = talkback.Offerings(cfg) if cfg.get("talk_back") else None
        # Today's sentences, so the clock can avoid repeating itself. Forgotten at midnight.
        self.memory_day = datetime.now().strftime("%Y-%m-%d")
        self.memory = self.load_memory(self.memory_day)

    def load_memory(self, day):
        path = os.path.join(self.cfg["archive_dir"], day + ".jsonl")
        texts = collections.OrderedDict()
        try:
            with open(path) as fh:
                for line in fh:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if entry.get("source") == "model":
                        texts[entry["key"]] = entry["text"]
        except OSError:
            pass
        return [texts[k] for k in sorted(texts)]

    def remember(self, moment, text):
        day = moment.strftime("%Y-%m-%d")
        if day != self.memory_day:
            self.memory_day, self.memory = day, []
        self.memory.append(text)

    def pick_thing(self, moment):
        """Something in the room the clock hasn't mentioned in its last 30 sentences."""
        things = self.cfg.get("things") or []
        if not things:
            return None
        said = content_words(" ".join(self.recent(moment, 30)))
        fresh = [t for t in things if not content_words(t) & said] or things
        return random.Random(minute_key(moment)).choice(fresh)

    def recent(self, moment, count):
        if moment.strftime("%Y-%m-%d") != self.memory_day:
            return []
        return self.memory[-count:] if count else []

    def observe(self, moment, fetch=True):
        try:
            return self.senses.observe(moment, fetch)
        except Exception as exc:  # a broken sense must never stop the clock
            log("senses failed:", repr(exc))
            return []

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
        return {
            "key": minute_key(moment),
            "lead": lead,
            "phrase": phrase,
            "text": "",
            "model": self.cfg["model"],
            "source": "pending",
        }

    def from_notebook(self, moment, reason):
        entry = self.skeleton(moment)
        rng = random.Random(entry["key"])
        entry.update(text=rng.choice(NOTEBOOK), source="notebook", reason=reason)
        return entry

    def compose(self, moment):
        entry = self.skeleton(moment)
        if time.time() < self.backoff_until:
            return self.from_notebook(moment, self.last_error or "model unavailable")
        temp_c = soc_temperature()
        observations = self.observe(moment)
        offering = self.offerings.take() if self.offerings else None
        checked = self.recent(moment, 12)
        thing = self.pick_thing(moment)
        messages = build_messages(self.cfg, entry["lead"], moment, observations, thing, offering)
        generate = generate_openai if self.cfg["backend"] == "openai" else generate_ollama
        started = time.time()
        try:
            # One second chance if the sentence breaks a rule; a Nano has time for two tries.
            for attempt in range(2):
                raw, stats = generate(self.cfg, messages)
                text = clean_continuation(raw, entry["lead"])
                if len(text.split()) < 3:
                    raise ValueError("reply too short: {!r}".format(raw))
                problem = contradiction(text, observations)
                if problem:
                    problem = "contradicts observations ({})".format(problem)
                elif offering and not talkback.uses_word(text, offering):
                    problem = 'left out "{}"'.format(offering)
                elif repeats(text, checked):
                    problem = "repeats: " + repeats(text, checked)
                if not problem:
                    break
                log("{} {}, asking again: {}".format(entry["key"], problem, text))
        except Exception as exc:  # anything at all -> the notebook; the clock must keep going
            if offering:
                self.offerings.put_back(offering)
            reason = getattr(exc, "reason", None) or exc
            self.last_error = str(reason)
            self.status = "offline"
            self.backoff_until = time.time() + 30
            log("model failed:", self.last_error)
            return self.from_notebook(moment, self.last_error)
        elapsed = time.time() - started
        stats.pop("first_token_at", None)
        confidence = word_confidences(text, stats.pop("token_probs", None))
        if offering and not talkback.uses_word(text, offering):
            self.offerings.put_back(offering)
            offering = None
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
            senses=[{"label": o["label"], "fact": o["fact"]} for o in observations],
            attempts=attempt + 1,
            confidence=confidence,
            offering=offering,
            thing=None if offering else thing,
            soc_temp=temp_c,
            written_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.remember(moment, text)
        log("{} {:.1f}s  {} {}{}".format(entry["key"], elapsed, entry["lead"], text,
                                        '  [word: {}]'.format(offering) if offering else ""))
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
    say_url = talkback.lan_url(cfg)

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
            if url.path == "/say":
                return self.static("/say.html")
            return self.static(url.path)

        def do_POST(self):
            if urlparse(self.path).path != "/api/say" or not author.offerings:
                return self.send_json({"ok": False, "message": "Not here."}, 404)
            length = min(int(self.headers.get("Content-Length") or 0), 1024)
            body = self.rfile.read(length).decode("utf-8", "replace")
            try:
                word = json.loads(body).get("word", "")
            except (ValueError, AttributeError):
                word = (parse_qs(body).get("word") or [""])[0]
            ok, message, position = author.offerings.offer(word, self.client_address[0])
            if not ok:
                return self.send_json({"ok": False, "message": message})
            # Next minute's sentence is usually written already, so the word lands after it.
            now = datetime.now().replace(second=0, microsecond=0)
            ahead = 1 if author.get(minute_key(now + timedelta(minutes=1))) else 0
            when = now + timedelta(minutes=position + ahead)
            self.send_json({"ok": True, "word": message, "at": when.strftime("%H:%M"),
                            "lead": timewords.lead(when.hour, when.minute)[0]})

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
                "outside": [o["label"] for o in author.observe(now, fetch=False)],
                "night": in_night(cfg, now.hour),
                "accent": cfg["accent"],
                "say_url": say_url if author.offerings else None,
                "words_waiting": author.offerings.waiting() if author.offerings else 0,
                "watts": cfg.get("watts", 10),
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
    if author.offerings:
        log("talk-back page:", talkback.lan_url(cfg))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
