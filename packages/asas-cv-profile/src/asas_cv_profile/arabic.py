"""Arabic as the checks read it: which characters are Arabic, and the letters folded so
that one word written two ways compares the same.

The folding is CAMeL Tools' (New York University Abu Dhabi, MIT licence): ``dediac_ar``
drops the diacritics, and ``normalize_alef_ar``, ``normalize_alef_maksura_ar`` and
``normalize_teh_marbuta_ar`` write each letter one way. The tatweel, a stretch mark with
no sound ("محـمد"), is dropped as well; the library leaves it.
"""

from __future__ import annotations

import re

from camel_tools.utils.dediac import dediac_ar
from camel_tools.utils.normalize import normalize_alef_ar, normalize_alef_maksura_ar, normalize_teh_marbuta_ar

#: the Arabic blocks: Arabic, its supplement and extended-A, and the presentation forms
#: some PDFs carry ("ﻣﺤﻤﺪ")
ARABIC = "؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿"
ARABIC_RE = re.compile(f"[{ARABIC}]")

_TATWEEL = "ـ"


def fold(text: str) -> str:
    """Diacritics and tatweel dropped, alef, alef maksura and teh marbuta written one way."""
    return normalize_teh_marbuta_ar(normalize_alef_maksura_ar(normalize_alef_ar(dediac_ar(text.replace(_TATWEEL, "")))))
