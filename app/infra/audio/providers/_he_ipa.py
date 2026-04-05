"""Rule-based Hebrew niqqud → IPA converter for LightBlueTTS.

Converts diacritized Hebrew text (with niqqud) to the IPA phoneme string
accepted by LightBlueTTS (lightblue_onnx).

The model vocabulary is:
    consonants : b v d h z χ t j k l m n s f p w ʔ ɡ ʁ ʃ ʒ
    vowels     : a e i o u
    stress     : ˈ  (primary stress marker, placed before stressed syllable)
    punctuation: space . , ! ? ' " - :

Characters outside the vocabulary are silently dropped (model maps them to
PAD token 0, which produces silence). Unknown consonants (e.g. tsadi צ/ץ)
are transliterated to their closest approximation or dropped.

References:
    IPA for Modern Israeli Hebrew (standard transliteration).
    Unicode niqqud block: U+05B0..U+05C7.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Unicode constants
# ---------------------------------------------------------------------------

# Niqqud vowel points (U+05B0..U+05BD, U+05C7)
_SHVA = "\u05B0"  # שְׁ  — shva (moving: ə; silent: dropped)
_HATAF_SEGOL = "\u05B1"  # חֱ  — e
_HATAF_PATAH = "\u05B2"  # חֲ  — a
_HATAF_KAMATZ = "\u05B3"  # חֳ  — o
_HIRIQ = "\u05B4"  # בִ  — i
_TSERE = "\u05B5"  # בֵ  — e
_SEGOL = "\u05B6"  # בֶ  — e
_PATAH = "\u05B7"  # בַ  — a
_KAMATZ = "\u05B8"  # בָ  — a  (kamatz gadol; kamatz katan = o, not distinguished here)
_HOLAM = "\u05B9"  # בֹ  — o
_HOLAM_MALE = "\u05BA"  # בֺ  — o  (rare variant)
_KUBUTS = "\u05BB"  # בֻ  — u
_DAGESH = "\u05BC"  # בּ  — dagesh (hardening; affects ב כ פ)
_METEG = "\u05BD"  # secondary stress — ignored
_MAQAF = "\u05BE"  # word-joining hyphen — replaced by space
_KAMATZ_KATAN = "\u05C7"  # קָ  — o (kamatz katan)
_SHURUK = "\u05BC"  # וּ  — u (vav + dagesh = shuruk; handled in context)
_RAFE = "\u05BF"  # soft mark — ignored

# Niqqud → IPA vowel map
_NIQQUD_VOWEL: dict[str, str] = {
    _SHVA: "",  # shva nah (silent) — drop; shva na (moving) → ə not in vocab
    _HATAF_SEGOL: "e",
    _HATAF_PATAH: "a",
    _HATAF_KAMATZ: "o",
    _HIRIQ: "i",
    _TSERE: "e",
    _SEGOL: "e",
    _PATAH: "a",
    _KAMATZ: "a",
    _HOLAM: "o",
    _HOLAM_MALE: "o",
    _KUBUTS: "u",
    _KAMATZ_KATAN: "o",
    _RAFE: "",
    _METEG: "",
}

# Hebrew letter → IPA consonant (base form, without dagesh)
_LETTER_BASE: dict[str, str] = {
    "\u05D0": "ʔ",  # א alef
    "\u05D1": "v",  # ב bet (soft, default without dagesh)
    "\u05D2": "ɡ",  # ג gimel
    "\u05D3": "d",  # ד dalet
    "\u05D4": "h",  # ה he
    "\u05D5": "v",  # ו vav (consonantal)
    "\u05D6": "z",  # ז zayin
    "\u05D7": "χ",  # ח het
    "\u05D8": "t",  # ט tet
    "\u05D9": "j",  # י yod (consonantal)
    "\u05DA": "χ",  # ך kaf sofit (soft)
    "\u05DB": "χ",  # כ kaf (soft, default)
    "\u05DC": "l",  # ל lamed
    "\u05DD": "m",  # ם mem sofit
    "\u05DE": "m",  # מ mem
    "\u05DF": "n",  # ן nun sofit
    "\u05E0": "n",  # נ nun
    "\u05E1": "s",  # ס samekh
    "\u05E2": "ʔ",  # ע ayin (glottal in modern Hebrew)
    "\u05E3": "f",  # ף pe sofit (soft)
    "\u05E4": "f",  # פ pe (soft, default)
    "\u05E5": "ts",  # ץ tsadi sofit → ts (dropped: not in vocab)
    "\u05E6": "ts",  # צ tsadi → ts (dropped: not in vocab)
    "\u05E7": "k",  # ק qof
    "\u05E8": "ʁ",  # ר resh
    "\u05E9": "ʃ",  # ש shin (default; sin handled via shin dot)
    "\u05EA": "t",  # ת tav
}

# Letters whose base form changes with dagesh (בּ כּ פּ)
_LETTER_DAGESH: dict[str, str] = {
    "\u05D1": "b",  # בּ bet with dagesh → b
    "\u05DB": "k",  # כּ kaf with dagesh → k
    "\u05DA": "k",  # ךּ kaf sofit with dagesh → k
    "\u05E4": "p",  # פּ pe with dagesh → p
    "\u05E3": "p",  # ףּ pe sofit with dagesh → p
}

# Shin dot / sin dot (U+05C1 shin dot, U+05C2 sin dot)
_SHIN_DOT = "\u05C1"
_SIN_DOT = "\u05C2"

# Cantillation marks range (U+0591–U+05AF) — stripped by the generation
# service sanitizer, but we strip again here defensively.
_CANTILLATION_RANGES = (
    ("\u0591", "\u05AF"),
    ("\u05C4", "\u05C5"),  # upper/lower dot
)

# Punctuation passthrough
_PUNCT_MAP: dict[str, str] = {
    " ": " ",
    "\t": " ",
    "\n": " ",
    ".": ".",
    ",": ",",
    "!": "!",
    "?": "?",
    "'": "'",
    "\u2019": "'",
    '"': '"',
    "-": "-",
    "\u2013": "-",
    "\u2014": "-",
    ":": ":",
}


def hebrew_to_ipa(text: str) -> str:
    """Convert diacritized Hebrew text to IPA phoneme string.

    Args:
        text: Hebrew text, ideally with niqqud diacritics.

    Returns:
        IPA string suitable for LightBlueTTS.create(phonemes).
    """
    if not text:
        return ""

    # Strip cantillation marks (defensive; sanitizer may have done this already)
    cleaned = _strip_cantillation(text)

    result: list[str] = []
    i = 0
    chars = list(cleaned)
    n = len(chars)

    last_vowel = ""  # tracks last vowel appended; used for mater lectionis detection

    while i < n:
        ch = chars[i]

        # --- Vav special cases (must be checked before generic letter branch) ---
        if ch == "\u05D5":
            j = i + 1
            # Shuruk: vav + dagesh (וּ) = /u/
            if j < n and chars[j] == _DAGESH:
                result.append("u")
                i = j + 1
                if i < n and chars[i] in (_HOLAM, _HOLAM_MALE):
                    i += 1
                continue
            # Holam male: vav + holam (וֹ) = /o/ — vav is mater lectionis, not consonant
            if j < n and chars[j] in (_HOLAM, _HOLAM_MALE):
                result.append("o")
                i = j + 1
                continue
            # Holam-male pattern: preceding consonant had holam → this vav is a
            # pure vowel letter (mater lectionis) and produces no additional sound.
            # Condition: last emitted vowel was 'o' (from holam on the previous
            # consonant) AND vav has no own vowel-producing niqqud.
            if last_vowel == "o" and not (j < n and chars[j] in (_DAGESH, _HOLAM, _HOLAM_MALE)):
                i += 1  # skip mater lectionis vav — sound already represented by 'o'
                continue
            # Otherwise treat as consonant /v/ (fall through to generic letter branch)

        # --- Hebrew letter ---
        if ch in _LETTER_BASE:
            # Pre-scan ALL diacritics following the letter to detect dagesh and
            # shin/sin dot, regardless of their order relative to vowel marks.
            # Unicode does not guarantee a canonical diacritic ordering in
            # user-generated or OCR text; scan up to the next base letter.
            _ALL_DIACRITICS = set(_NIQQUD_VOWEL.keys()) | {
                _DAGESH,
                _SHIN_DOT,
                _SIN_DOT,
                _HOLAM,
                _HOLAM_MALE,
                _METEG,
                _RAFE,
                _MAQAF,
            }
            dagesh = False
            shin_dot = ""
            j = i + 1
            while j < n and chars[j] in _ALL_DIACRITICS:
                if chars[j] == _DAGESH:
                    dagesh = True
                elif chars[j] == _SHIN_DOT:
                    shin_dot = "shin"
                elif chars[j] == _SIN_DOT:
                    shin_dot = "sin"
                j += 1
            end_diacritics = j  # first char after all diacritics of this letter

            # Resolve consonant IPA
            if ch == "\u05E9":  # shin/sin
                cons = "s" if shin_dot == "sin" else "ʃ"
            elif dagesh and ch in _LETTER_DAGESH:
                cons = _LETTER_DAGESH[ch]
            else:
                cons = _LETTER_BASE[ch]

            # Yod mater lectionis: yod with no own vowel after /i/ = silent.
            # e.g. אֲנִי — hiriq on nun, final yod is mater lectionis.
            has_own_vowel = any(
                chars[k] in _NIQQUD_VOWEL or chars[k] in (_HOLAM, _HOLAM_MALE)
                for k in range(i + 1, end_diacritics)
            )
            is_yod_ml = ch == "\u05D9" and last_vowel == "i" and not dagesh and not has_own_vowel
            if not is_yod_ml and cons != "ts":
                result.append(cons)

            # Collect vowel niqqud (second pass through the same diacritics)
            # Gutturals: א ה ח ע — mobile shva (shva na) before these is pronounced /e/.
            _GUTTURALS = {"\u05D0", "\u05D4", "\u05D7", "\u05E2"}
            next_base = chars[end_diacritics] if end_diacritics < n else ""
            vowel_here = ""
            k = i + 1
            while k < end_diacritics:
                c = chars[k]
                if c in _NIQQUD_VOWEL:
                    v = _NIQQUD_VOWEL[c]
                    # Mobile shva (shva na) before a guttural letter → /e/.
                    if c == _SHVA and v == "" and next_base in _GUTTURALS:
                        v = "e"
                    if v:
                        result.append(v)
                        vowel_here = v
                elif c in (_HOLAM, _HOLAM_MALE):
                    result.append("o")
                    vowel_here = "o"
                k += 1

            if vowel_here:
                last_vowel = vowel_here

            i = end_diacritics
            continue

        # --- Punctuation / space ---
        if ch in _PUNCT_MAP:
            mapped = _PUNCT_MAP[ch]
            # Collapse consecutive spaces
            if mapped == " " and result and result[-1] == " ":
                pass
            else:
                result.append(mapped)
            last_vowel = ""  # reset across word boundaries
            i += 1
            continue

        # --- Maqaf (word-joining hyphen) → space ---
        if ch == _MAQAF:
            if result and result[-1] != " ":
                result.append(" ")
            last_vowel = ""
            i += 1
            continue

        # --- Lone niqqud mark (already consumed in letter branch normally) ---
        if ch in _NIQQUD_VOWEL:
            v = _NIQQUD_VOWEL[ch]
            if v:
                result.append(v)
                last_vowel = v
            i += 1
            continue

        # --- Everything else: skip silently ---
        i += 1

    phonemes = "".join(result).strip()
    # Normalise multiple spaces
    import re  # noqa: PLC0415

    phonemes = re.sub(r" {2,}", " ", phonemes)
    return phonemes


def _strip_cantillation(text: str) -> str:
    """Remove cantillation marks from Hebrew text."""
    result = []
    for ch in text:
        cp = ord(ch)
        skip = False
        for lo, hi in _CANTILLATION_RANGES:
            if ord(lo) <= cp <= ord(hi):
                skip = True
                break
        if not skip:
            result.append(ch)
    return "".join(result)
