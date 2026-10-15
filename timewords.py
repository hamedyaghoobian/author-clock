"""Turn a clock reading into the words a person would say.

Kept dependency-free (no inflect) so it runs on the Jetson Nano's stock Python 3.6.
"""

ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
TENS = ["", "", "twenty", "thirty", "forty", "fifty"]


def number_words(n):
    """0-59 in words: 23 -> 'twenty-three'."""
    if n < 20:
        return ONES[n]
    tens, ones = divmod(n, 10)
    return TENS[tens] + ("-" + ONES[ones] if ones else "")


def hour_words(hour24):
    if hour24 % 24 == 0:
        return "midnight"
    if hour24 % 24 == 12:
        return "noon"
    return number_words(hour24 % 12)


def time_phrase(hour, minute):
    """'quarter past two', 'seven minutes to noon', 'midnight'."""
    if minute == 0:
        name = hour_words(hour)
        return name if name in ("midnight", "noon") else name + " o'clock"
    if minute == 15:
        return "quarter past " + hour_words(hour)
    if minute == 30:
        return "half past " + hour_words(hour)
    if minute == 45:
        return "quarter to " + hour_words(hour + 1)

    if minute < 30:
        count, relation, target = minute, "past", hour
    else:
        count, relation, target = 60 - minute, "to", hour + 1

    if count % 5 == 0:
        amount = number_words(count)
    elif count == 1:
        amount = "one minute"
    else:
        amount = number_words(count) + " minutes"
    return "{} {} {}".format(amount, relation, hour_words(target))


def daypart(hour):
    if 1 <= hour < 5:
        return "in the small hours"
    if 5 <= hour < 12:
        return "in the morning"
    if 12 <= hour < 17:
        return "in the afternoon"
    if 17 <= hour < 21:
        return "in the evening"
    return "at night"


def lead(hour, minute):
    """The fixed opening of every sentence: 'At quarter past two in the afternoon,'.

    Returns (lead, phrase) so the display can set the time phrase apart.
    """
    phrase = time_phrase(hour, minute)
    if "noon" in phrase or "midnight" in phrase:
        when = phrase
    else:
        when = phrase + " " + daypart(hour)
    return "At " + when + ",", when


if __name__ == "__main__":
    for h, m in [(0, 0), (0, 20), (2, 7), (11, 45), (12, 0), (12, 31), (14, 15), (23, 59)]:
        print("{:02d}:{:02d}  {}".format(h, m, lead(h, m)[0]))
