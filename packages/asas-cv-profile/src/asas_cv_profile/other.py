"""The lines no field took: shown as runs worth a look, and kept as other information.

Every content line no field took goes to the section of kind ``other_information``, one
entry per heading it sits under (the field with role ``topic``: the heading; ``details``:
the lines), so nothing the CV says is lost. Left out: lines under a referees or
personal-details heading, personal facts, and lines with an email, a link or a phone
number. One short call names each block's kind and the lines elsewhere that already say
what it says; code checks that claim before a block is left out as a repeat.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import calls, checks
from .answers import cited_text, personal
from .headings import Headings, has, marked, title
from .lines import Lines
from .model import ProfileModel, Section, Spec
from .seams import Ask, CallResult

#: content lines in a row that no entry cites, worth a look
UNCITED_RUN = 8
#: headings whose lines the profile keeps nowhere: referees are other people, and
#: personal details are either fields already or facts the profile must not hold
KEEP_OUT = ("references", "reference", "referees", "personal details", "personal information", "contact",
            "المراجع", "المعلومات الشخصية", "البيانات الشخصية")
CONTACT = re.compile(r"@|https?://|www\.|(?<!\d)(?:\+|00)?\d(?:[\s().-]?\d){8,}(?!\d)", re.IGNORECASE)
#: a block is a repeat only when this share of its numbers and Latin words are in the
#: lines it repeats or in a line a field cites: the model says which lines, code checks it
REPEAT_MARKS = 0.8
_MARK = re.compile(r"[a-z][a-z+#.]+|\d+")


def marks(text: str) -> set[str]:
    """Numbers and Latin words, a plural as its singular ("KPIs" is "KPI")."""
    return {m[:-1] if len(m) > 3 and m.endswith("s") and not m.isdigit() else m for m in _MARK.findall(checks.norm(text))}


@dataclass(frozen=True)
class Target:
    """Where other information goes: the section, and its fields for the heading, the
    lines and (when it has one) the block's kind."""

    section: Section
    topic: Spec
    details: Spec
    kind: Spec | None


class OtherLines:
    """The lines no field took, for one profile model. ``target`` is None when the model
    has no section of kind ``other_information`` with a topic and a details field: the
    lines are then still counted, and kept nowhere."""

    def __init__(self, model: ProfileModel, headings: Headings):
        self.headings = headings
        self.section: Section | None = model.first("other_information")
        s = self.section
        topic, details = (s.role("topic"), s.role("details")) if s else (None, None)
        self.target = Target(s, topic, details, s.role("kind")) if s and topic and details else None

    @property
    def usable(self) -> bool:
        return self.target is not None

    def cited(self, profile: dict) -> set[int]:
        """Every line an entry or a text field cites, other information left out: it is made from the rest."""
        cited: set[int] = set()
        s = self.section
        for cat, subs in profile.items():
            for sub, node in subs.items():
                if s and (cat, sub) == (s.group, s.name):
                    continue
                for e in node if isinstance(node, list) else [node]:
                    cited.update(e.get("lines") or [])
                    for cell in (e.get("fields") or {}).values():
                        cited.update(cell.get("lines") or [])
        return cited

    def uncited(self, profile: dict, text: Lines) -> list[list[int]]:
        """Runs of UNCITED_RUN or more content lines no entry and no text field cites, as
        [first, last, count]: something missed, or what the profile has no field for.
        Other information does not count as citing them, so a miss still shows."""
        cited = self.cited(profile)
        runs: list[list[int]] = []
        current: list[int] = []
        for n, line in enumerate(text.lines, 1):
            if n in cited:
                if current:
                    runs.append(current)
                current = []
            elif sum(ch.isalpha() for ch in line) >= 3 and self.headings.heading(line) is None:
                current.append(n)
        if current:
            runs.append(current)
        return [[r[0], r[-1], len(r)] for r in runs if len(r) >= UNCITED_RUN]

    def blocks(self, profile: dict, text: Lines, skip: frozenset[int] = frozenset()) -> list[dict]:
        """Every content line no field took, one entry per heading it sits under. ``skip``:
        lines found to repeat what the profile already holds."""
        if (t := self.target) is None:
            return []
        cited = self.cited(profile) | skip
        keep_out_words = tuple(checks.norm(w) for w in KEEP_OUT)
        found: dict[int, tuple[str, list[int]]] = {}
        at, topic, keep_out = 0, "Before any heading", False
        for n, line in enumerate(text.lines, 1):
            h = self.headings.heading(line)
            if h is None and n not in cited and marked(line):
                h = set()  # "##### ADDITIONAL INFORMATION": a heading the word lists do not know is still a new topic
            if h is not None:
                at, topic = n, title(line)
                keep_out = not h and any(has(checks.norm(topic), w) for w in keep_out_words)
                continue
            if n in cited or keep_out or sum(ch.isalpha() for ch in line) < 3 or personal(line) or CONTACT.search(line):
                continue
            found.setdefault(at, (topic, []))[1].append(n)
        return [{"lines": nums, "fields": {
                    t.topic.name: {"kind": "copied", "check": "unplaced", "value": topic},
                    t.details.name: {"kind": "text", "lines": nums, "check": "unplaced", "value": "\n".join(text.line(n) or "" for n in nums)}}}
                for _, (topic, nums) in sorted(found.items())]

    def held(self, profile: dict) -> list[dict]:
        s = self.section
        return (profile.get(s.group) or {}).get(s.name) or [] if s else []

    def counts(self, profile: dict) -> dict:
        other = self.held(profile)
        return {"lines": sum(len(e["lines"]) for e in other), "topics": len(other)}

    def put(self, profile: dict, text: Lines, skip: frozenset[int] = frozenset()) -> dict:
        """Other information made again from the profile as it stands, in place; how many
        lines and topics it holds. A block keeps the kind it was given before, matched by
        its first line."""
        if (t := self.target) is None:
            return {"lines": 0, "topics": 0}
        s, kind_f = t.section, t.kind
        before = profile.get(s.group, {}).pop(s.name, None) or []
        kinds = {e["lines"][0]: e["fields"][kind_f.name] for e in before if kind_f and kind_f.name in e["fields"] and e.get("lines")}
        other = self.blocks(profile, text, skip)
        if kind_f:
            for e in other:
                if e["lines"][0] in kinds:
                    e["fields"][kind_f.name] = kinds[e["lines"][0]]
        if other:
            profile.setdefault(s.group, {})[s.name] = other
        return self.counts(profile)

    async def name(self, profile: dict, text: Lines, ask: Ask) -> tuple[CallResult, list[dict]]:
        """Each block gets its kind, and a block that only repeats lines the profile already
        holds is left out: a bilingual CV puts its Arabic summary, skills and header there,
        because the fields cite the English copy. A repeat must point at lines that stay out
        of other information (a field cites them, or they were left out on purpose, such as
        contact lines) or sit in an earlier block that stays; and the block's numbers and
        Latin words ("IPSAS", "RPA", "25") must be in those lines or in a line a field cites
        (a stray English degree line in an Arabic block). What was left out is listed."""
        if (t := self.target) is None:
            raise ValueError("the profile model has no other information section to name")
        s, topic_f, kind_f = t.section, t.topic, t.kind
        blocks = self.held(profile)
        kinds = tuple(kind_f.values) if kind_f and kind_f.values else calls.OTHER_KINDS
        res = await calls.kind_other(ask, [(e["fields"][topic_f.name]["value"], e["lines"]) for e in blocks], text.numbered(), kinds)
        cited = self.cited(profile)
        covered = set(range(1, len(text.lines) + 1)) - {n for e in blocks for n in e["lines"]}
        held = marks(" \n".join(text.line(n) or "" for n in sorted(cited)))
        gone, dropped = set(), []
        said = {b.block: b for b in getattr(res.output, "blocks", None) or [] if 1 <= b.block <= len(blocks)}
        for i, e in enumerate(blocks, 1):
            b = said.get(i)
            if b is None:
                covered |= set(e["lines"])
                continue
            if kind_f:
                e["fields"][kind_f.name] = {"kind": "normalised", "check": "unplaced", "value": b.kind}
            reps = sorted({n for n in b.repeats if text.line(n) is not None and n not in e["lines"]})
            own = marks(" \n".join(text.line(n) or "" for n in e["lines"]))
            theirs = marks(cited_text(reps, text)) | held
            if reps and set(reps) <= covered and (not own or len(own & theirs) >= REPEAT_MARKS * len(own)):
                gone.add(i)
                dropped.append({"lines": e["lines"], "repeats": reps, "topic": e["fields"][topic_f.name]["value"]})
            else:
                covered |= set(e["lines"])
        if gone:
            kept = [e for i, e in enumerate(blocks, 1) if i not in gone]
            if kept:
                profile[s.group][s.name] = kept
            else:
                del profile[s.group][s.name]
        return res, dropped
