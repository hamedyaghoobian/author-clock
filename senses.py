"""What the clock knows about the world outside the window.

Each sense returns a dict {"label": short rail text, "fact": a plain sentence for the
prompt} or None when it has nothing to say. Facts are worded qualitatively ("the sun set
a little while ago", "cool") so the model doesn't parrot numbers back.

Standard library only, Python 3.6+.
"""
import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib import request as urlrequest

# ---------------------------------------------------------------------------- the sun

SUNRISE_ALTITUDE = -0.833  # degrees; accounts for refraction and the sun's radius


def solar_elevation(when_utc, lat, lon):
    """Sun's altitude in degrees (NOAA low-precision formulas, good to ~0.5 deg)."""
    n = when_utc.timestamp() / 86400.0 + 2440587.5 - 2451545.0
    mean_long = (280.460 + 0.9856474 * n) % 360
    anomaly = math.radians((357.528 + 0.9856003 * n) % 360)
    ecl_long = math.radians(mean_long + 1.915 * math.sin(anomaly) + 0.020 * math.sin(2 * anomaly))
    obliquity = math.radians(23.439 - 0.0000004 * n)
    ra = math.atan2(math.cos(obliquity) * math.sin(ecl_long), math.cos(ecl_long))
    dec = math.asin(math.sin(obliquity) * math.sin(ecl_long))
    gmst_hours = (18.697374558 + 24.06570982441908 * n) % 24
    hour_angle = math.radians(gmst_hours * 15 + lon) - ra
    lat_r = math.radians(lat)
    return math.degrees(math.asin(
        math.sin(lat_r) * math.sin(dec) + math.cos(lat_r) * math.cos(dec) * math.cos(hour_angle)))


_sun_days = {}


def sun_times(day_local, lat, lon):
    """(sunrise, sunset) as aware datetimes for the local calendar day, or None for either
    if the sun doesn't cross the horizon. Found by scanning in two-minute steps."""
    key = (day_local.date(), lat, lon)
    if key not in _sun_days:
        start = day_local.replace(hour=0, minute=0, second=0, microsecond=0)
        rise = set_ = None
        prev = solar_elevation(start.astimezone(timezone.utc), lat, lon)
        for step in range(1, 721):
            t = start + timedelta(minutes=2 * step)
            cur = solar_elevation(t.astimezone(timezone.utc), lat, lon)
            if prev < SUNRISE_ALTITUDE <= cur and rise is None:
                rise = t
            elif prev >= SUNRISE_ALTITUDE > cur and set_ is None:
                set_ = t
            prev = cur
        _sun_days.clear()
        _sun_days[key] = (rise, set_)
    return _sun_days[key]


# Light words each phase rules out; the author asks again if a sentence uses them.
_NOT_NIGHT = r"\b(moon\w*|stars?|starlight|midnight|darkness|night\w*)\b"
_NOT_SUNSET = r"\b(sunset|setting sun|dusk|twilight|evening light|sun ?rise|dawn)\b"
_NOT_DAY = r"\b(sunlight|sunshine|sunbeams?|sunlit|midday|afternoon sun|morning sun)\b"
CONTRADICTS = {
    "night": _NOT_DAY + "|" + _NOT_SUNSET,
    "daylight": _NOT_NIGHT + "|" + _NOT_SUNSET,
    "high sun": _NOT_NIGHT + "|" + _NOT_SUNSET,
}


def sense_sun(now_local, lat, lon):
    observation = _sun_phase(now_local, lat, lon)
    if observation["label"] in CONTRADICTS:
        observation["contradicts"] = CONTRADICTS[observation["label"]]
    return observation


def _sun_phase(now_local, lat, lon):
    elevation = solar_elevation(now_local.astimezone(timezone.utc), lat, lon)
    rise, set_ = sun_times(now_local, lat, lon)

    def minutes(a, b):
        return (b - a).total_seconds() / 60.0

    if rise and now_local < rise:
        to_rise = minutes(now_local, rise)
        if to_rise <= 40:
            return {"label": "dawn", "fact": "Outside the window, dawn is breaking; the sun is about to rise."}
        if elevation > -12:
            return {"label": "first light", "fact": "Outside, the sky is just starting to pale before dawn."}
        return {"label": "night", "fact": "It is still dark outside, hours before sunrise."}
    if set_ and now_local > set_:
        since_set = minutes(set_, now_local)
        if since_set <= 40:
            return {"label": "dusk", "fact": "The sun has just set; dusk is settling outside the window."}
        if elevation > -12:
            return {"label": "last light", "fact": "Outside, the last light of the day is fading."}
        return {"label": "night", "fact": "It is dark outside; the sun went down hours ago."}
    if rise and set_:
        if minutes(rise, now_local) < 60:
            return {"label": "sunrise", "fact": "The sun has only just risen and the light outside is low and pale."}
        if minutes(now_local, set_) < 60:
            return {"label": "golden hour", "fact": "The sun is low and golden outside; it will set soon."}
        if elevation > 50:
            return {"label": "high sun", "fact": "It is bright daylight outside, the sun high overhead."}
        return {"label": "daylight", "fact": "It is daylight outside."}
    # Polar day or night.
    if elevation > 0:
        return {"label": "daylight", "fact": "It is daylight outside."}
    return {"label": "night", "fact": "It is dark outside."}


# ---------------------------------------------------------------------------- the weather

WMO = {
    0: "clear skies", 1: "mostly clear skies", 2: "partly cloudy skies", 3: "an overcast sky",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "a thunderstorm", 96: "a thunderstorm with hail", 99: "a thunderstorm with hail",
}


def feel(temp_c):
    for limit, word in ((0, "freezing"), (8, "cold"), (15, "cool"), (22, "mild"), (28, "warm")):
        if temp_c < limit:
            return word
    return "hot"


def wind_words(kmh):
    if kmh < 6:
        return "still air"
    if kmh < 20:
        return "a light breeze"
    if kmh < 40:
        return "a strong wind"
    return "a gale"


class Weather(object):
    """Current conditions from Open-Meteo (free, no key), refreshed every 15 minutes.
    Keeps the last good reading for two hours if the network drops."""

    URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=temperature_2m,weather_code,wind_speed_10m,is_day&wind_speed_unit=kmh")

    def __init__(self, lat, lon, refresh=900, stale_after=7200):
        self.lat, self.lon = lat, lon
        self.refresh, self.stale_after = refresh, stale_after
        self.reading, self.fetched_at, self.tried_at = None, 0, 0
        self.lock = threading.Lock()

    def fetch(self):
        url = self.URL.format(lat=self.lat, lon=self.lon)
        req = urlrequest.Request(url, headers={"User-Agent": "author-clock"})
        with urlrequest.urlopen(req, timeout=6) as resp:
            current = json.loads(resp.read().decode("utf-8"))["current"]
        return {"temp_c": float(current["temperature_2m"]), "code": int(current["weather_code"]),
                "wind_kmh": float(current["wind_speed_10m"]), "is_day": bool(current.get("is_day", 1))}

    def sense(self, fetch=True):
        """fetch=False only reads the cache, so the display's once-a-second poll never waits
        on the network; the author thread does the fetching."""
        now = time.time()
        with self.lock:
            due = fetch and now - self.tried_at > self.refresh
            if due:
                self.tried_at = now
        if due:
            try:
                reading = self.fetch()
                with self.lock:
                    self.reading, self.fetched_at = reading, time.time()
            except Exception:
                pass  # keep the last reading; the clock works without weather
        with self.lock:
            if not self.reading or now - self.fetched_at > self.stale_after:
                return None
            r = self.reading
        sky = WMO.get(r["code"], "unsettled weather")
        # Describe only what's there. Telling a small model "it is not raining" makes it
        # write about rain.
        if r["code"] <= 1:
            sky = "sunshine and clear skies" if r["is_day"] else "a clear night sky"
        fact = "Outside it is {}, with {} and {}.".format(feel(r["temp_c"]), sky, wind_words(r["wind_kmh"]))
        label = "{} · {:.0f} °C".format(WMO.get(r["code"], "unsettled weather").replace("an overcast sky", "overcast").replace("a thunderstorm", "thunderstorm"),
                                        r["temp_c"])
        observation = {"label": label, "fact": fact}
        if r["code"] < 45:
            # Words a sentence may not use while it's dry; the author asks again if it does.
            observation["contradicts"] = r"\b(rain\w*|drizzl\w*|storm\w*|snow\w*|puddles?|raindrops?|droplets?|downpour)\b"
        return observation


# ---------------------------------------------------------------------------- all together

class Senses(object):
    def __init__(self, cfg):
        self.lat, self.lon = cfg.get("latitude"), cfg.get("longitude")
        located = self.lat is not None and self.lon is not None
        self.weather = Weather(self.lat, self.lon) if located and cfg.get("weather", True) else None

    def observe(self, moment, fetch=True):
        """Observations for a (naive, local) minute, as a list of {"label", "fact"}."""
        found = []
        if self.lat is not None and self.lon is not None:
            found.append(sense_sun(moment.astimezone(), self.lat, self.lon))
        if self.weather:
            reading = self.weather.sense(fetch)
            if reading:
                found.append(reading)
        return found


if __name__ == "__main__":
    import sys
    lat, lon = float(sys.argv[1]), float(sys.argv[2])
    now = datetime.now().astimezone()
    rise, set_ = sun_times(now, lat, lon)
    print("sunrise", rise and rise.strftime("%H:%M"), "sunset", set_ and set_.strftime("%H:%M"))
    for h in range(0, 24):
        t = now.replace(hour=h, minute=0, second=0, microsecond=0)
        print(t.strftime("%H:%M"), "{:6.1f}".format(solar_elevation(t.astimezone(timezone.utc), lat, lon)),
              sense_sun(t, lat, lon)["label"])
    print(Weather(lat, lon).sense())
