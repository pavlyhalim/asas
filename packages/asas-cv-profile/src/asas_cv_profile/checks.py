"""Every value checked against the lines it cites.

Each value gets one word:

- `verified`: the value is in the cited lines (dates and numbers by what they say,
  not how they are written).
- `normalised`: an enum or a yes/no the model chose from a list; the CV's own
  words differ by design, so it is shown with its lines for a person to judge.
- `inferred`: not in the lines, and the profile model allows the field to be worked out.
- `unverified`: not in the lines, and the field should have been copied. Kept,
  never dropped, and listed first in the review.
- `bad_lines`: the entry cites no line the text has. A range past the end, or back to
  front, is dropped and the value is checked against the ranges that are real.
- `computed`: worked out in code (:mod:`asas_cv_profile.experience`, or the host).

Libraries, not hand rules: Arabic letter folding from CAMeL Tools (NYU Abu Dhabi, in
:mod:`.arabic`), fuzzy matching from RapidFuzz, dates from dateparser with CLDR's
locale data (every Arabic region's month names) and its Hijri calendar.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from rapidfuzz import fuzz, process

from .arabic import ARABIC, ARABIC_RE, fold

MATCH = 90  # RapidFuzz partial ratio a copied value must reach in its lines
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


SHORT = 3  # a value this short after folding ("R", "AI", "SQL") is only found as a whole word
_RUN = re.compile(r"\d+")
_MARKED = re.compile(r"\w[+#]+")  # C++, C#, F#: the marks are part of the name


def norm(text: str) -> str:
    s = fold(unicodedata.normalize("NFKC", str(text)).casefold().translate(DIGITS))
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def found(value: str, haystack: str) -> bool:
    """The value is in the text: as written, or within RapidFuzz's partial or token-set
    ratio of :data:`MATCH`. Three things a ratio cannot see are checked first: its numbers
    must be there exactly ("Level 4" is not "Level 5"), a name whose marks are part of it
    must keep them ("C++" is not "C#"), and one short word, or one Latin word, is found as
    a word ("R" is not in "reports", "Java" is not "JavaScript"). A longer Arabic word keeps
    the plain rule: Arabic writes "and" and "the" onto the word ("والرياض")."""
    v, h = norm(value), norm(haystack)
    if not v:
        return not str(value).strip()  # nothing to find; a value of marks alone is not in any text
    if not set(_RUN.findall(v)) <= set(_RUN.findall(h)):
        return False
    raw = unicodedata.normalize("NFKC", str(haystack)).casefold()
    if any(m not in raw for m in _MARKED.findall(unicodedata.normalize("NFKC", str(value)).casefold())):
        return False
    if " " not in v and (len(v) <= SHORT or not ARABIC_RE.search(v)):
        return process.extractOne(v, h.split(), scorer=fuzz.ratio, score_cutoff=MATCH) is not None
    return v in h or fuzz.partial_ratio(v, h) >= MATCH or fuzz.token_set_ratio(v, h) >= MATCH


#: Dates are read by dateparser from CLDR's locale data, never from a list of ours. It
#: takes one region of a language per call, so each Arabic region is tried in turn: Arabic
#: as the Gulf and Egypt write it, the Levant and Iraq (أيلول، كانون الثاني), Algeria and
#: Tunisia (جانفي), Morocco (شتنبر). Its text search is limited (its docs say so) and takes
#: no regional locale, so the words before each year are parsed instead: on a set of Arabic
#: CVs the search over whole cited passages missed 48 of the 50 dates it flagged ("June 2025",
#: "7/6/2011", "يناير 2020", "2019م"), all of them in the lines.
LOCALES = {"latin": (["en"],), "arabic": (["ar"], ["ar-SY"], ["ar-DZ"], ["ar-MA"])}
_SETTINGS = {"PREFER_DAY_OF_MONTH": "first", "REQUIRE_PARTS": ["year", "month"], "DATE_ORDER": "DMY"}
#: Egypt's spellings of June and July, which CLDR does not carry
_EGYPT = {"يونيه": "يونيو", "يوليه": "يوليو"}
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_TOKEN = re.compile(r"[^\W\d_]+\.?|\d+|[^\w\s]")  # words, numbers and marks, so "2010.Cyberjaya" gives up its year
_AFTER = re.compile(r"[\s,]+([^\W\d_]{3,}\.?)")
_ERA = re.compile(rf"(\d{{4}})\s*م(?![{ARABIC}])")  # 2019م: the Gregorian era mark
_DAYS = r"\d{1,2}(?:\s?[-–]\s?\d{1,2})?"  # a day, or a range of days
#: numbers only, the same in every language: 2019-05, 7/6/2011 (day first, as the UAE writes), 6/2011, 8-11/12 2011
_YM = re.compile(r"(?<!\d)((?:19|20)\d{2})[-/.](\d{1,2})(?!\d)")
_DMY = re.compile(rf"(?<![\d/.\-])(?:{_DAYS}\s?[/.\-])?(\d{{1,2}})[/.\-]\s?((?:19|20)\d{{2}})(?!\d)")
_DM_Y = re.compile(rf"(?<![\d/.\-]){_DAYS}\s?[/.\-](\d{{1,2}})\s+((?:19|20)\d{{2}})(?!\d)")
_HIJRI = re.compile(r"(?<![\d/.\-])(?:\d{1,2}[/.\-]\d{1,2}[/.\-]1[34]\d{2}|1[34]\d{2}[/.\-]\d{1,2}[/.\-]\d{1,2})(?![\d/.\-])")


@lru_cache(maxsize=16384)
def named_month(phrase: str) -> tuple[int, int] | None:
    """(year, month) of a short phrase holding a month's name, read by dateparser."""
    import dateparser

    script = "arabic" if ARABIC_RE.search(phrase) else "latin"
    for word, standard in _EGYPT.items():
        phrase = phrase.replace(word, standard)
    for locales in LOCALES[script]:
        when = dateparser.parse(phrase, locales=locales, settings=_SETTINGS)
        if when:
            return when.year, when.month
    return None


def _hijri(text: str) -> set[tuple[int, int]]:
    """Full Hijri dates in numbers (15/3/1440), as the Gregorian month they fall in."""
    from dateparser.calendars.hijri import HijriCalendar

    out = set()
    for found_ in _HIJRI.findall(text):
        got = HijriCalendar(found_).get_date()
        if got and got.period == "day":
            out.add((got.date_obj.year, got.date_obj.month))
    return out


@lru_cache(maxsize=4096)
def _months_in(text: str) -> frozenset[tuple[int, int | None]]:
    """Every (year, month) the text states; month None for a year alone."""
    text = _ERA.sub(r"\1", text.translate(DIGITS))
    out: set[tuple[int, int | None]] = {(int(y), None) for y in _YEAR.findall(text)}
    out |= {(int(y), int(m)) for y, m in _YM.findall(text) if 1 <= int(m) <= 12}
    out |= {(int(y), int(m)) for rx in (_DMY, _DM_Y) for m, y in rx.findall(text) if 1 <= int(m) <= 12}
    out |= _hijri(text)
    for line in text.splitlines():
        toks = list(_TOKEN.finditer(line))
        for i, tok in enumerate(toks):
            if not _YEAR.fullmatch(tok.group()):
                continue
            # the words before the year ("June 2025", "15th March, 2019", "كانون الثاني 2015")
            for k in range(1, 6):
                if i - k < 0:
                    break
                phrase = line[toks[i - k].start():tok.end()]
                if re.search(r"[^\W\d_]{3,}", phrase) and (got := named_month(phrase)):
                    out.add(got)
                    break
            # or the month after it, as reference lists write it ("2025 Dec;47(3)"), never across a dash
            after = _AFTER.match(line, tok.end())
            if after and (got := named_month(f"{tok.group()} {after.group(1)}")):
                out.add(got)
    return frozenset(out)


def date_found(value: str, cited: str) -> bool:
    """YYYY, YYYY-MM or YYYY-MM-DD, found by year and month in however the CV writes it."""
    m = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-\d{1,2})?$", str(value).strip())
    if not m:
        return False
    year, month = int(m.group(1)), int(m.group(2)) if m.group(2) else None
    stated = _months_in(cited)
    return (year, month) in stated if month else any(y == year for y, _ in stated)


_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def _numbers_in(text: str) -> set[float]:
    """Every number the text states, "2.1 million" and "1,500,000" included."""
    out = set()
    for num, unit in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|mn|million|m|bn|billion|b)?\b", text.translate(DIGITS).lower()):
        n = float(num.replace(",", ""))
        out.add(n)
        if unit:
            out.add(round(n * _SCALE[unit], 2))
    return out


def year_only(value, cited: str) -> str | None:
    """The year alone, when the model wrote a month the lines do not give: the lines state
    the year with no month at all (on one set of CVs, 30 of the 35 dates flagged as not
    found were "2019" in the CV written "2019-03"). None when the value stands or the lines give
    another month, which is a real mismatch."""
    m = re.match(r"^(\d{4})-\d{1,2}(?:-\d{1,2})?$", str(value or "").strip())
    if not m:
        return None
    stated = _months_in(cited)
    year = int(m.group(1))
    return m.group(1) if (year, None) in stated and not any(y == year and mo for y, mo in stated) else None


def phone_found(value, cited: str) -> bool:
    """Each number the same number as one in the lines, compared by Google's libphonenumber
    (the phonenumbers port), so "+971501234567" is found where the CV writes "050 123 4567".
    A number with no country code is read as a UAE one."""
    import phonenumbers

    def national(text: str) -> str | None:
        try:
            return str(phonenumbers.parse(text, "AE").national_number)
        except phonenumbers.NumberParseException:
            return None

    in_lines = {str(m.number.national_number) for m in phonenumbers.PhoneNumberMatcher(cited.translate(DIGITS), "AE", leniency=phonenumbers.Leniency.POSSIBLE)}
    digits = re.sub(r"\D", "", cited.translate(DIGITS))
    for v in value if isinstance(value, list) else [value]:
        n = national(str(v))
        if not n or not (n in in_lines or (len(n) >= 7 and n in digits)):
            return False
    return True


def check_value(spec, value, cited: str, lines_ok: bool) -> str:
    if value in (None, "", [], "Not stated"):
        return "empty"  # nothing to check, whatever the lines: an empty field is not a bad one
    if not lines_ok:
        return "bad_lines"
    if spec.type == "phone":
        return "verified" if phone_found(value, cited) else "unverified"
    if spec.kind == "text":
        return "verified"  # copied from the lines by code, so it is the CV's text by construction
    if spec.type in ("date", "year"):
        return "verified" if date_found(value, cited) else ("inferred" if spec.may_infer else "unverified")
    if spec.type == "number":
        return "verified" if round(float(value), 2) in _numbers_in(cited) else ("inferred" if spec.may_infer else "unverified")
    if spec.kind == "copied":
        if found(str(value), cited):
            return "verified"
        return "inferred" if spec.may_infer else "unverified"
    # enums, multi enums, booleans: chosen from a list
    values = value if isinstance(value, list) else [value]
    if all(isinstance(v, str) and found(v, cited) for v in values):
        return "verified"
    return "inferred" if spec.may_infer else "normalised"
