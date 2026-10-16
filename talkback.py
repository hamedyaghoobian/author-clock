"""Words people in the lab give the clock, one at a time, from their phones.

A word is accepted if it is a single plain word (letters, apostrophes, hyphens), isn't on
the blocklist, and its sender hasn't offered one in the last minute. Accepted words wait in
a short queue; the author takes one per minute and must use it in that sentence.

Standard library only, Python 3.6+.
"""
import collections
import os
import re
import socket
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
WORD_RE = re.compile(r"^[a-z][a-z'\-]{1,23}$")
LEET = str.maketrans("013457@$!", "oieastasi")


def _squash(word):
    """'fuuuck' -> 'fuck', 'sh1t' -> 'shit': undo the usual ways around a filter."""
    word = word.translate(LEET)
    word = re.sub(r"[^a-z]", "", word)
    return re.sub(r"(.)\1+", r"\1", word)


def load_blocklist(path):
    """(whole_words, inside_words): lines starting with * are also caught inside words."""
    whole, inside = set(), set()
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip().lower()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("*"):
                    line = line[1:]
                    inside.add(_squash(line))
                whole.add(line)
    except OSError:
        pass
    return whole, inside


class Offerings(object):
    def __init__(self, cfg):
        self.queue = collections.deque()
        self.max_queue = cfg.get("talk_back_queue", 30)
        self.cooldown = cfg.get("talk_back_cooldown", 60)
        self.last_by_sender = {}
        self.tries = {}
        self.lock = threading.Lock()
        path = cfg.get("blocklist") or os.path.join(ROOT, "blocklist.txt")
        self.blocked, self.blocked_inside = load_blocklist(path)
        self.blocked_squashed = {_squash(w) for w in self.blocked}

    def check(self, word):
        """(clean_word, None) if acceptable, else (None, reason for the sender)."""
        word = (word or "").strip().lower()
        if " " in word:
            return None, "Just one word, please."
        if not WORD_RE.match(word):
            return None, "Letters only, two to twenty-four of them."
        squashed = _squash(word)
        if (word in self.blocked or squashed in self.blocked_squashed
                or any(b in squashed for b in self.blocked_inside)):
            return None, "The clock won't write that one. It's on the lab wall."
        return word, None

    def offer(self, raw_word, sender):
        """Returns (ok, message, position_in_queue)."""
        word, problem = self.check(raw_word)
        if problem:
            return False, problem, None
        now = time.time()
        with self.lock:
            last = self.last_by_sender.get(sender, 0)
            if now - last < self.cooldown:
                wait = int(self.cooldown - (now - last)) + 1
                return False, "One word a minute. Try again in {} s.".format(wait), None
            if len(self.queue) >= self.max_queue:
                return False, "The clock has plenty of words waiting. Try again in a few minutes.", None
            self.queue.append(word)
            self.last_by_sender[sender] = now
            # Forget old senders so the table doesn't grow all semester.
            for key in [k for k, t in self.last_by_sender.items() if now - t > 3600]:
                del self.last_by_sender[key]
            return True, word, len(self.queue)

    def take(self):
        with self.lock:
            return self.queue.popleft() if self.queue else None

    def put_back(self, word):
        """The model didn't manage to use it; give it one more minute, then let it go."""
        with self.lock:
            self.tries[word] = self.tries.get(word, 0) + 1
            if self.tries[word] < 2:
                self.queue.appendleft(word)
            else:
                del self.tries[word]

    def waiting(self):
        with self.lock:
            return len(self.queue)


def uses_word(text, word):
    """Did the sentence use the word (or an inflection of it: nebula -> nebulae)?"""
    stem = word if len(word) <= 4 else word[:-1]
    return re.search(r"\b" + re.escape(stem) + r"[a-z'\-]*\b", text, re.I) is not None


def lan_url(cfg):
    """The address phones on the lab network should open."""
    if cfg.get("public_url"):
        return cfg["public_url"].rstrip("/") + "/say"
    ip = None
    try:
        # No packet is sent; this just asks the OS which interface would route outward.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        pass
    if not ip or ip.startswith("127."):
        ip = socket.gethostname() + ".local"
    return "http://{}:{}/say".format(ip, cfg["port"])
