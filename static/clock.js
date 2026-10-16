// Author Clock — polls the local server once a second and stages each minute's sentence.
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var els = {
    stage: $("stage"), sentence: $("sentence"), measure: $("measure"), ghost: $("ghost"),
    outside: $("outside"), qr: $("qr"), qrcode: $("qrcode"), qrurl: $("qrurl"), ritual: $("ritual"),
    index: $("index"), hhmm: $("hhmm"), date: $("date"),
    meta: $("meta"), aside: $("aside"), day: $("day"), minute: $("minute"),
  };

  var shownKey = null;      // "2026-10-15T12:47|model"
  var clockOffset = 0;      // server time minus browser time, in ms
  var typingTimer = null;
  var lastState = null;
  var lastPollOk = 0;       // browser time of the last successful poll

  // Same wording as timewords.py, so the page can show the right time on its own
  // when the server is down instead of freezing on an old minute.
  var ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
  var TENS = ["", "", "twenty", "thirty", "forty", "fifty"];
  function numberWords(n) {
    return n < 20 ? ONES[n] : TENS[Math.floor(n / 10)] + (n % 10 ? "-" + ONES[n % 10] : "");
  }
  function hourWords(h) {
    h = h % 24;
    return h === 0 ? "midnight" : h === 12 ? "noon" : numberWords(h % 12);
  }
  function timePhrase(h, m) {
    if (m === 0) { var n = hourWords(h); return n === "midnight" || n === "noon" ? n : n + " o'clock"; }
    if (m === 15) return "quarter past " + hourWords(h);
    if (m === 30) return "half past " + hourWords(h);
    if (m === 45) return "quarter to " + hourWords(h + 1);
    var count = m < 30 ? m : 60 - m, rel = m < 30 ? "past" : "to", target = m < 30 ? h : h + 1;
    var amount = count % 5 === 0 ? numberWords(count) : count === 1 ? "one minute" : numberWords(count) + " minutes";
    return amount + " " + rel + " " + hourWords(target);
  }
  function daypart(h) {
    if (h >= 1 && h < 5) return "in the small hours";
    if (h >= 5 && h < 12) return "in the morning";
    if (h >= 12 && h < 17) return "in the afternoon";
    if (h >= 17 && h < 21) return "in the evening";
    return "at night";
  }
  function minuteKey(t) {
    return t.getFullYear() + "-" + pad(t.getMonth() + 1) + "-" + pad(t.getDate()) +
      "T" + pad(t.getHours()) + ":" + pad(t.getMinutes());
  }
  function localEntry(t) {
    var phrase = timePhrase(t.getHours(), t.getMinutes());
    var when = /noon|midnight/.test(phrase) ? phrase : phrase + " " + daypart(t.getHours());
    return { key: minuteKey(t), lead: "At " + when + ",", phrase: when, text: "", source: "local" };
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function now() { return new Date(Date.now() + clockOffset); }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // How sure the model was of a word, 0..1, from the probability of its least likely
  // token: p=1 -> 1, p=0.1 -> 0.5, p=0.01 -> 0. Missing (older Ollama) -> fully sure.
  function certainty(entry, i) {
    var p = entry.confidence && entry.confidence[i];
    if (p == null) return 1;
    return Math.max(0, Math.min(1, 1 + Math.log(Math.max(p, 1e-4)) / Math.LN10 / 2));
  }

  function isGift(entry, word) {
    if (!entry.offering) return false;
    var stem = entry.offering.length > 4 ? entry.offering.slice(0, -1) : entry.offering;
    return word.toLowerCase().replace(/^[^a-z]+/, "").indexOf(stem) === 0;
  }

  // "At " + <em>quarter past two in the afternoon</em> + "," then the body, word by word,
  // each word split into letters so it can erode over the minute.
  function sentenceHtml(entry, revealAll) {
    var lead = escapeHtml(entry.lead);
    var phrase = escapeHtml(entry.phrase);
    var leadHtml = lead.replace(phrase, '<span class="when">' + phrase + "</span>");
    var words = entry.text ? entry.text.split(/\s+/) : [];
    var body = words.map(function (w, i) {
      var c = certainty(entry, i);
      var cls = "word" + (revealAll ? " on" : "") + (c < 0.35 ? " unsure" : "") + (isGift(entry, w) ? " gift" : "");
      var letters = w.split("").map(function (ch) { return '<span class="l">' + escapeHtml(ch) + "</span>"; }).join("");
      return '<span class="' + cls + '" style="--c:' + c.toFixed(2) + '" data-c="' + c.toFixed(2) + '">' + letters + "</span>";
    }).join(" ");
    return leadHtml + ' <span class="body">' + body + "</span>";
  }

  // The sentence exists for one minute, and you can watch it go: letters fade to a ghost
  // between ~24 s and ~57 s, least certain words first, the lab's word last.
  function scheduleDecay(entry, typingMs) {
    if (!entry.text) return;
    var minuteStart = new Date(entry.key + ":00").getTime();
    var t = now().getTime();
    var start = Math.max(minuteStart + 24000, t + typingMs + 4000);
    var end = minuteStart + 57000;
    if (end - start < 6000) { start = t + 1000; end = Math.max(end, start + 6000); }
    var s = els.sentence;
    var letters = s.querySelectorAll(".word .l");
    void s.offsetWidth;  // letters must render solid before their fade is scheduled
    for (var i = 0; i < letters.length; i++) {
      var word = letters[i].parentNode;
      var c = parseFloat(word.getAttribute("data-c"));
      var order = word.classList.contains("gift") ? 1 : 0.7 * c + 0.3 * Math.random();
      var delay = start + order * (end - start - 2400) - t;
      letters[i].style.transition = "opacity 2.4s ease-in " + Math.max(0, Math.round(delay)) + "ms";
      letters[i].style.opacity = "0.07";
    }
  }

  // Largest font size at which the full sentence fits the stage.
  function fitSize(entry) {
    var m = els.measure;
    m.style.maxWidth = els.sentence.style.maxWidth || "";
    m.innerHTML = sentenceHtml(entry, true) + '<span class="caret"></span>';
    var vw = window.innerWidth / 100;
    var maxH = els.stage.clientHeight - 6 * vw;
    var lo = 2.2 * vw, hi = 7.2 * vw;
    for (var i = 0; i < 14; i++) {
      var mid = (lo + hi) / 2;
      m.style.fontSize = mid + "px";
      if (m.offsetHeight <= maxH) lo = mid; else hi = mid;
    }
    return lo;
  }

  function render(entry) {
    clearTimeout(typingTimer);
    var s = els.sentence;
    s.classList.add("fading");
    setTimeout(function () {
      document.body.classList.toggle("notebook", entry.source === "notebook");
      s.style.fontSize = fitSize(entry) + "px";
      s.innerHTML = sentenceHtml(entry, false);
      s.classList.remove("done");
      drift();
      s.classList.remove("fading");
      scheduleDecay(entry, typeOut(entry));
    }, shownKey ? 650 : 0);
  }

  // Reveal words at the pace the model actually produced them (capped so the
  // sentence is readable for most of its minute).
  function typeOut(entry) {
    var s = els.sentence;
    var caret = document.createElement("span");
    caret.className = "caret";
    var words = s.querySelectorAll(".word");
    if (!words.length) {          // pending: just the lead and a blinking caret
      s.appendChild(caret);
      return 0;
    }
    s.insertBefore(caret, s.querySelector(".body"));

    var cps = entry.chars_per_second || 16;
    var total = entry.text.length / cps * 1000;
    var scale = Math.max(2500, Math.min(total, 14000)) / total;
    var i = 0;
    (function step() {
      var w = words[i];
      w.classList.add("on");
      w.parentNode.insertBefore(caret, w.nextSibling);
      i++;
      if (i >= words.length) {
        s.appendChild(caret);
        s.classList.add("done");
        return;
      }
      var chars = words[i].textContent.length + 1;
      var jitter = 0.75 + Math.random() * 0.5;
      typingTimer = setTimeout(step, chars / cps * 1000 * scale * jitter);
    })();
    return total * scale;
  }

  // A few pixels of wander each minute so nothing burns into the panel.
  function drift() {
    var x = Math.round((Math.random() - 0.5) * 16);
    var y = Math.round((Math.random() - 0.5) * 12);
    els.sentence.style.transform = "translate(" + x + "px," + y + "px)";
  }

  function part(k, v) {
    return '<span class="k">' + escapeHtml(k) + '</span> <span class="v">' + escapeHtml(v) + "</span>";
  }
  var SEP = ' <span class="sep">/</span> ';

  function renderMeta(state) {
    var e = state.entry;
    var bits = [];
    if (e.source === "model") {
      bits.push(part("model", e.model));
      if (e.tokens) bits.push(part("tokens", e.tokens));
      if (e.tokens_per_second) bits.push(part("speed", e.tokens_per_second + " tok/s"));
      if (e.seconds != null) bits.push(part("written in", e.seconds + " s"));
      bits.push(part("temp", e.temperature));
    } else if (e.source === "notebook") {
      bits.push(part("model", e.reason === "warming up" ? "warming up" : "unreachable"));
      bits.push('<span class="v">reading from the notebook</span>');
    } else {
      bits.push(part("model", state.model));
      bits.push('<span class="v">composing…</span>');
    }
    els.meta.innerHTML = bits.join(SEP);

    // What the clock perceived: for a written sentence, exactly what the model was told.
    var outside = e.source === "model" && e.senses ? e.senses.map(function (o) { return o.label; }) : state.outside || [];
    var top = outside.length ? [part("outside", outside.join(" · "))] : [];
    if (e.offering) top.push(part("word from the lab", e.offering));
    els.outside.innerHTML = top.join(SEP);
    renderQr(state);

    var aside = [];
    if (e.source === "model" && e.written_at) {
      var ahead = Math.round((new Date(e.key + ":00") - new Date(e.written_at)) / 1000);
      if (ahead > 0) aside.push(part("written", ahead + " s before this minute existed"));
    }
    if (state.soc_temp != null) aside.push(part("soc", state.soc_temp.toFixed(1) + " °C"));
    if (!aside.length) aside.push("this sentence exists for one minute");
    els.aside.innerHTML = aside.join(SEP);
  }

  function tickClock() {
    var t = now();
    var hh = pad(t.getHours()), mm = pad(t.getMinutes());
    els.hhmm.textContent = hh + ":" + mm + ":" + pad(t.getSeconds());
    els.ghost.textContent = hh + ":" + mm;
    els.date.textContent = t.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    var mod = t.getHours() * 60 + t.getMinutes();
    els.index.textContent = "№ " + ("000" + mod).slice(-4) + " / 1440";
    els.day.style.transform = "scaleX(" + (mod / 1440) + ")";
    maybeRitual(t);

    // Server silent for a few seconds: never leave an old minute on the wall.
    var key = minuteKey(t);
    if (Date.now() - lastPollOk > 3000 && (!shownKey || shownKey.split("|")[0] !== key)) {
      render(localEntry(t));
      shownKey = key + "|local";
    }
  }

  // The accent hairline sweeps once per minute; CSS does the animating.
  var minuteSwept = null;
  function sweepMinute() {
    var t = now();
    var key = t.getHours() * 60 + t.getMinutes();
    if (key === minuteSwept) return;
    minuteSwept = key;
    var elapsed = t.getSeconds() + t.getMilliseconds() / 1000;
    var m = els.minute;
    m.style.transition = "none";
    m.style.transform = "scaleX(" + elapsed / 60 + ")";
    void m.offsetWidth;
    m.style.transition = "transform " + (60 - elapsed) + "s linear";
    m.style.transform = "scaleX(1)";
  }

  // ---- talk-back: a QR code to the /say page --------------------------------------

  var qrFor = null;
  function renderQr(state) {
    if (state.say_url === qrFor) return;
    qrFor = state.say_url;
    if (!state.say_url || typeof qrcode !== "function") { els.qr.style.display = "none"; return; }
    var qr = qrcode(0, "M");
    qr.addData(state.say_url);
    qr.make();
    var n = qr.getModuleCount(), d = "";
    for (var r = 0; r < n; r++) {
      for (var c = 0; c < n; c++) if (qr.isDark(r, c)) d += "M" + c + " " + r + "h1v1h-1z";
    }
    els.qrcode.innerHTML = '<svg viewBox="-2 -2 ' + (n + 4) + " " + (n + 4) + '" shape-rendering="crispEdges">' +
      '<rect x="-2" y="-2" width="' + (n + 4) + '" height="' + (n + 4) + '" class="qr-bg"/><path d="' + d + '" class="qr-fg"/></svg>';
    els.qrurl.textContent = state.say_url.replace(/^https?:\/\//, "");
    els.qr.style.display = "";
  }

  // ---- the midnight ritual -------------------------------------------------------------
  // At 23:59:12 the day's sentences stream past, then the whole book appears at once as a
  // wall of tiny type with the day's tally, then everything clears and the clock forgets.
  // Ends at 00:00:00, when "At midnight," starts the new day. ?ritual=1 rehearses it now.

  var ritualFor = null;

  function isoDate(t) { return t.getFullYear() + "-" + pad(t.getMonth() + 1) + "-" + pad(t.getDate()); }

  function maybeRitual(t) {
    if (t.getHours() === 23 && t.getMinutes() === 59 && t.getSeconds() >= 12 && t.getSeconds() < 30 &&
        ritualFor !== isoDate(t)) {
      startRitual(isoDate(t));
    }
  }

  function tally(entries, watts) {
    var words = 0, tokens = 0, seconds = 0, gifts = [];
    entries.forEach(function (e) {
      words += (e.lead + " " + e.text).split(/\s+/).length;
      tokens += e.tokens || 0;
      seconds += e.seconds || 0;
      if (e.offering) gifts.push(e.offering);
    });
    var wh = seconds * (watts || 10) / 3600;
    var h = Math.floor(seconds / 3600), m = Math.round((seconds % 3600) / 60);
    return { sentences: entries.length, words: words, tokens: tokens, gifts: gifts, wh: wh,
             thinking: (h ? h + " h " : "") + m + " min" };
  }

  function fmt(n) { return Math.round(n).toLocaleString("en-US"); }

  function startRitual(date) {
    ritualFor = date;
    var watts = lastState && lastState.watts;
    fetch("/api/book?date=" + date, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (book) { runRitual(book.entries || [], watts); })
      .catch(function () {});
  }

  function runRitual(entries, watts) {
    var ov = els.ritual;
    var t = tally(entries, watts);
    var lines = entries.map(function (e) {
      return '<p><span class="k">' + e.key.slice(11) + "</span> " + escapeHtml(e.lead + " " + e.text) + "</p>";
    }).join("");
    var all = entries.map(function (e) { return escapeHtml(e.lead + " " + e.text); }).join(" ");
    var gifts = t.gifts.length
      ? "<p>" + t.gifts.length + (t.gifts.length === 1 ? " word" : " words") + " came from the lab: <em>" +
        escapeHtml(t.gifts.slice(-14).join(", ")) + (t.gifts.length > 14 ? ", …" : "") + "</em></p>"
      : "";
    var wh = t.wh < 10 ? t.wh.toFixed(1) : fmt(t.wh);
    ov.innerHTML =
      '<div class="r-scroll" id="r-scroll">' + lines + "</div>" +
      '<div class="r-wall" id="r-wall"><p>' + all + "</p></div>" +
      '<div class="r-tally" id="r-tally">' +
        '<p class="k">today the clock wrote</p>' +
        '<p class="big">' + fmt(t.sentences) + " sentences</p>" +
        "<p>" + fmt(t.words) + " words · " + fmt(t.tokens) + " tokens · " + t.thinking + " of thinking</p>" +
        "<p>about " + wh + " Wh of electricity, cooled by one small fan. No water.</p>" + gifts +
        '<p class="k forget">now it forgets</p>' +
      "</div>";
    ov.className = "ritual on";
    document.body.classList.add("in-ritual");

    // 1. Stream: the day scrolls past, slow at first, then a blur.
    var scroll = $("r-scroll");
    var h = scroll.scrollHeight;
    scroll.style.transform = "translateY(" + Math.round(window.innerHeight * 0.45) + "px)";
    void scroll.offsetWidth;
    scroll.style.transition = "transform 28s cubic-bezier(.6,0,.95,.55)";
    scroll.style.transform = "translateY(" + (-h) + "px)";

    // 2. The whole book at once, as texture, with the tally over it.
    setTimeout(function () {
      var wall = $("r-wall");
      var chars = Math.max(all.length, 1);
      var size = Math.sqrt(window.innerWidth * window.innerHeight / (chars * 0.62));
      wall.style.fontSize = Math.max(2, Math.min(size, 28)) + "px";
      ov.classList.add("wall");
    }, 29000);

    // 3. Clear.
    setTimeout(function () { ov.classList.add("clear"); }, 43000);
    setTimeout(function () {
      ov.className = "ritual";
      ov.innerHTML = "";
      document.body.classList.remove("in-ritual");
    }, 47500);
  }

  function poll() {
    var sent = Date.now();
    fetch("/api/now", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (state) {
        var rtt = Date.now() - sent;
        clockOffset = state.now * 1000 - (sent + rtt / 2);
        lastState = state;
        lastPollOk = Date.now();
        document.body.classList.toggle("night", !!state.night);
        if (state.accent) document.documentElement.style.setProperty("--accent", state.accent);
        var key = state.entry.key + "|" + state.entry.source;
        if (key !== shownKey) {
          render(state.entry);
          shownKey = key;
        }
        renderMeta(state);
      })
      .catch(function () {
        els.meta.innerHTML = '<span class="v">clock server unreachable — retrying</span>';
      });
  }

  window.addEventListener("resize", function () {
    if (lastState) { shownKey = null; render(lastState.entry); shownKey = lastState.entry.key + "|" + lastState.entry.source; }
  });

  setInterval(function () { tickClock(); sweepMinute(); }, 250);
  setInterval(poll, 1000);
  tickClock();
  sweepMinute();
  poll();
  if (/[?&]ritual=1/.test(location.search)) setTimeout(function () { startRitual(isoDate(now())); }, 1500);
})();
