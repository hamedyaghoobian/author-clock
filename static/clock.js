// Author Clock — polls the local server once a second and stages each minute's sentence.
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var els = {
    stage: $("stage"), sentence: $("sentence"), measure: $("measure"), ghost: $("ghost"),
    voice: $("voice"), index: $("index"), hhmm: $("hhmm"), date: $("date"),
    meta: $("meta"), aside: $("aside"), day: $("day"), minute: $("minute"),
  };

  var shownKey = null;      // "2026-10-15T12:47|model"
  var clockOffset = 0;      // server time minus browser time, in ms
  var typingTimer = null;
  var lastState = null;

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function now() { return new Date(Date.now() + clockOffset); }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // "At " + <em>quarter past two in the afternoon</em> + "," then the body, word by word.
  function sentenceHtml(entry, revealAll) {
    var lead = escapeHtml(entry.lead);
    var phrase = escapeHtml(entry.phrase);
    var leadHtml = lead.replace(phrase, '<span class="when">' + phrase + "</span>");
    var words = entry.text ? entry.text.split(/\s+/) : [];
    var body = words.map(function (w) {
      return '<span class="word' + (revealAll ? " on" : "") + '">' + escapeHtml(w) + "</span>";
    }).join(" ");
    return leadHtml + ' <span class="body">' + body + "</span>";
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
      typeOut(entry);
    }, shownKey ? 650 : 0);
    els.voice.textContent = entry.voice || "—";
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
      return;
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

  function poll() {
    var sent = Date.now();
    fetch("/api/now", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (state) {
        var rtt = Date.now() - sent;
        clockOffset = state.now * 1000 - (sent + rtt / 2);
        lastState = state;
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
})();
