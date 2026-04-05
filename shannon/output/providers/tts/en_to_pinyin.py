"""English text → pinyin phoneme conversion for Chinese Piper voices.

Uses espeak-ng (bundled with piper) to phonemize English text into IPA,
then maps IPA phonemes to the closest Mandarin pinyin equivalents based
on standard Chinese transliteration conventions (e.g. hello → 哈喽 ha-lou).

The result is lossy — English sounds that don't exist in Mandarin are
approximated, producing a Chinese-accented rendering.

Key phonetic considerations:
- Pinyin ``e`` alone = [ɤ] (mid-back unrounded), NOT schwa — English [ə]
  maps to ``a`` instead.
- Chinese has no voiced fricatives [v, ð, ʒ] or dental fricatives [θ, ð].
- Mandarin syllable structure is (C)V(n/ng) — no consonant clusters,
  no coda stops. Stranded consonants get an epenthetic vowel.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

# ---------------------------------------------------------------------------
# IPA → pinyin mapping tables
# ---------------------------------------------------------------------------

# IPA consonant → pinyin initial (onset)
# Based on standard Chinese transliteration conventions:
#   θ→t, ð→d (dental fricatives → corresponding stops; "think"→"tink", "this"→"dis")
#   v→w (Victoria→维 wei, visa→维 wei)
#   ʒ→zh, ʃ→sh (measure→没热 ~ zh, ship→十 shi)
_CONS_MAP: dict[str, str] = {
    "p": "p",
    "b": "b",
    "m": "m",
    "f": "f",
    "t": "t",
    "d": "d",
    "n": "n",
    "l": "l",
    "k": "k",
    "g": "g",
    "ɡ": "g",   # IPA g (U+0261) — espeak uses this
    "h": "h",
    "s": "s",
    "z": "z",
    "ʃ": "sh",
    "ʒ": "zh",
    "θ": "t",
    "ð": "d",
    "ɹ": "r",
    "r": "r",
    "w": "w",
    "j": "y",   # IPA j = English /y/
    "v": "w",   # 维 wei — standard Chinese approximation of [v]
    "ŋ": "",    # velar nasal — handled as coda, not onset
    "ɾ": "d",   # alveolar tap (AmE "butter", "little") → d (closest stop)
    "ʔ": "",    # glottal stop — no Mandarin equivalent, skip
}

# Two-char IPA affricates (checked before single-char lookup)
_AFFRICATE_MAP: dict[str, str] = {
    "tʃ": "ch",
    "dʒ": "zh",
    "ts": "z",
    "dz": "z",
}

# IPA vowel/diphthong → pinyin final
# Ordered longest-first so multi-char sequences match before components.
#
# Phonetic rationale for non-obvious mappings:
#   ə→a : pinyin "e" = [ɤ], nothing like schwa; 哈 ha is closer
#   æ→a : open front [æ] ≈ open central [a]; cat→卡特 ka-te
#   ɛ→ei : [ɛ] ≈ start of [eɪ]; bed→贝德 bei-de
#   ʌ→a : [ʌ] is mid-back; cup→卡普 ka-pu, bus→巴士 ba-shi
#   ɔɪ→ao : [ɔɪ] ≈ [aʊ] reversed-ish; boy→宝伊 bao-yi (close enough)
#   ɜː→er : nurse vowel [ɜ] ≈ pinyin er [aɚ] (both rhotic/central)
#   ɚ→er : rhotic schwa, same target
_VOWEL_MAP: list[tuple[str, str]] = [
    # Diphthongs / long sequences (3-char, 2-char)
    ("aɪ", "ai"),
    ("aʊ", "ao"),
    ("eɪ", "ei"),
    ("ɔɪ", "ao"),    # boy → bao; not perfect but closest available
    ("oʊ", "ou"),
    ("əʊ", "ou"),
    ("ɪə", "ie"),
    ("ʊə", "ue"),
    # Long monophthongs
    ("ɜː", "er"),
    ("ɑː", "a"),
    ("iː", "i"),
    ("uː", "u"),
    ("ɔː", "o"),
    # Short monophthongs
    ("ɑ", "a"),
    ("æ", "a"),      # cat → ka-te (卡特)
    ("ɐ", "a"),      # near-open central ≈ a
    ("ə", "a"),      # schwa → a (pinyin "e" = [ɤ], not schwa!)
    ("ɚ", "er"),     # rhotic schwa → er
    ("ɛ", "ei"),     # bed → bei-de (贝德)
    ("ɪ", "i"),
    ("ʊ", "u"),
    ("ɒ", "o"),      # BrE lot vowel
    ("ɔ", "o"),
    ("ʌ", "a"),      # cup → ka-pu (卡普), bus → ba-shi (巴士)
    ("ɜ", "er"),     # nurse vowel without length mark
    ("a", "a"),
    ("e", "ei"),     # espeak "e" in [eɪ] diphthong context
    ("i", "i"),
    ("o", "ou"),
    ("u", "u"),
]

# Default epenthetic vowel for stranded consonants (no following vowel).
# Based on standard Chinese transliteration:
#   s→斯(si), z→兹(zi), sh→什(shi), zh→之(zhi), ch→吃(chi), r→日(ri)
#   p→普(pu), b→布(bu), m→姆(mu), f→夫(fu)
#   t→特(te), d→德(de), k→克(ke), g→格(ge)
#   l→勒(le), n→恩(en), h→赫(he)
_STRAY_VOWEL: dict[str, str] = {
    "s": "i",  "z": "i",  "sh": "i", "zh": "i", "ch": "i", "r": "i",
    "p": "u",  "b": "u",  "m": "u",  "f": "u",
}
# Everything else defaults to "e" (te, de, ke, ge, le, ne, he)

# Coda consonants that merge into the final (nasal codas)
_NASAL_CODAS: dict[str, dict[str, str]] = {
    "n": {
        "a": "an",  "ai": "an",  "ao": "an",
        "ei": "en", "e": "en",   "er": "en",
        "i": "in",  "ie": "ian", "ia": "ian",
        "u": "un",  "ue": "uan", "ua": "uan",
        "o": "en",  "ou": "en",
    },
    "ŋ": {
        "a": "ang",  "ai": "ang",  "ao": "ang",
        "ei": "eng", "e": "eng",   "er": "eng",
        "i": "ing",  "ie": "iang", "ia": "iang",
        "u": "ong",  "ue": "uang", "ua": "uang",
        "o": "ong",  "ou": "eng",
    },
    "m": {  # no -m coda in Mandarin; approximate as -n
        "a": "an",  "ai": "an",  "ao": "an",
        "ei": "en", "e": "en",   "er": "en",
        "i": "in",  "ie": "ian", "ia": "ian",
        "u": "un",  "ue": "uan", "ua": "uan",
        "o": "en",  "ou": "en",
    },
}

# IPA characters that are vowels / vowel-like
_IPA_VOWELS = set("aeiouɑæɐəɛɪʊɒɔʌɜɚ")

# IPA sibilants — always kept in coda (si5/zi5/shi5 are essentially syllabic)
_IPA_SIBILANTS = set("szʃʒ")

# IPA stops — always dropped in coda (Mandarin has no coda stops)
_IPA_STOPS = set("pbtdkgɡʔ")

# Mandarin palatalization: dental/retroflex sibilants → palatal before
# high-front finals (i, ia, ie, ian, in, iang, ing, etc.).
# Prevents illegal combos like *si=[sɿ] when the target is [si].
_PALATALIZE: dict[str, str] = {
    "s": "x", "z": "j",
    "sh": "x", "zh": "j", "ch": "q",
}


# IPA characters to skip entirely (stress marks, length marks, ties, etc.)
_SKIP = set("ˈˌː̩̃ˑ͡")

# Punctuation passthrough (these exist in the pinyin phoneme_id_map)
_PUNCTUATION_MAP: dict[str, str] = {
    ".": ".", ",": ",", "!": "!", "?": "?",
    ":": ":", ";": ";", " ": " ",
    "—": "—", "…": "…",
}


# ---------------------------------------------------------------------------
# Core converter
# ---------------------------------------------------------------------------

def _is_vowel(ch: str) -> bool:
    return ch in _IPA_VOWELS


def _match_vowel(ipa: Sequence[str], pos: int) -> tuple[str, int, bool]:
    """Match the longest vowel sequence starting at *pos*.

    Returns (pinyin_final, new_pos, is_schwa).
    *is_schwa* is True when the matched IPA was a bare ``ə`` — callers
    use this to remap unstressed schwas from ``a`` to ``e``.
    """
    for length in (3, 2, 1):
        if pos + length > len(ipa):
            continue
        chunk = "".join(ipa[pos:pos + length])
        for ipa_v, py_v in _VOWEL_MAP:
            if chunk == ipa_v:
                is_schwa = (chunk == "ə")
                return py_v, pos + length, is_schwa
    # Fallback for unknown vowel-like codepoints
    return "a", pos + 1, False


def _match_consonant(ipa: Sequence[str], pos: int) -> tuple[str, int]:
    """Match a consonant (affricate first, then single char).

    Returns (pinyin_initial, new_pos).
    """
    if pos + 1 < len(ipa):
        pair = ipa[pos] + ipa[pos + 1]
        if pair in _AFFRICATE_MAP:
            return _AFFRICATE_MAP[pair], pos + 2

    ch = ipa[pos]
    if ch in _CONS_MAP:
        return _CONS_MAP[ch], pos + 1

    # Unknown consonant — skip
    return "", pos + 1


def ipa_to_pinyin(
    ipa_phonemes: list[str],
    stressed: set[int] | None = None,
    secondary_stressed: set[int] | None = None,
) -> list[str]:
    """Convert a flat list of IPA codepoints to pinyin phoneme tokens.

    Each Mandarin syllable is emitted as ``[initial, final, tone]`` where
    *initial* may be ``"Ø"`` (null onset).

    Tone assignment:
    - Primary stress (ˈ) → tone 4 (falling — emphatic)
    - Secondary stress (ˌ) → tone 2 (rising)
    - Unstressed → tone 1 (flat)
    """
    if stressed is None:
        stressed = set()
    if secondary_stressed is None:
        secondary_stressed = set()

    result: list[str] = []
    pos = 0
    n = len(ipa_phonemes)

    while pos < n:
        ch = ipa_phonemes[pos]

        # --- skip modifiers / combining marks ---
        if ch in _SKIP or unicodedata.category(ch).startswith("M"):
            if ch == "ˈ":
                stressed.add(pos + 1)
            elif ch == "ˌ":
                secondary_stressed.add(pos + 1)
            pos += 1
            continue

        # --- length mark (stray) ---
        if ch == "ː":
            pos += 1
            continue

        # --- punctuation passthrough ---
        if ch in _PUNCTUATION_MAP:
            result.append(_PUNCTUATION_MAP[ch])
            pos += 1
            continue

        # --- begin syllable ---
        initial = "Ø"
        final = ""
        is_primary = pos in stressed
        is_secondary = pos in secondary_stressed

        # Onset consonant(s) — in English there can be clusters (str-, pl-).
        # Mandarin allows only one initial, so extra consonants become
        # separate syllables with epenthetic vowels.
        onset_queue: list[str] = []
        while pos < n and not _is_vowel(ipa_phonemes[pos]) and ipa_phonemes[pos] not in _PUNCTUATION_MAP:
            p = ipa_phonemes[pos]
            if p in _SKIP or unicodedata.category(p).startswith("M"):
                if p == "ˈ":
                    is_primary = True
                elif p == "ˌ":
                    is_secondary = True
                pos += 1
                continue
            if p == "ː":
                pos += 1
                continue
            cons, pos = _match_consonant(ipa_phonemes, pos)
            if cons:
                onset_queue.append(cons)
            # Empty string from _match_consonant means unknown — already skipped

        # Check whether a vowel follows the onset cluster.
        has_vowel = pos < n and _is_vowel(ipa_phonemes[pos])

        # When no vowel follows, these are stray codas.  Kept codas are
        # now handled inline in the coda loop, so anything reaching here
        # as a vowel-less onset was already decided to be kept by the
        # coda logic (sibilant or stressed).  Just drop empties.
        if not has_vowel and onset_queue:
            if not onset_queue:
                continue

        # Emit extra onset consonants as separate syllables (epenthesis).
        # Smart vowel: if the next consonant in the queue is a semivowel,
        # borrow its vowel color (w→u, y→i).  "squirrel" sk-w… → si-ku-w…
        if onset_queue:
            for idx, extra_c in enumerate(onset_queue[:-1]):
                next_c = onset_queue[idx + 1]
                if next_c == "w":
                    ev = "u"
                elif next_c == "y":
                    ev = "i"
                else:
                    ev = _STRAY_VOWEL.get(extra_c, "e")
                result.extend([extra_c, ev, "5"])
            initial = onset_queue[-1]
        # else: no onset, initial stays "Ø"

        # Nucleus vowel
        was_schwa = False
        is_real_vowel = False  # True when final came from IPA, not epenthesis
        if has_vowel:
            final, pos, was_schwa = _match_vowel(ipa_phonemes, pos)
            is_real_vowel = True
            # Skip trailing length mark
            while pos < n and ipa_phonemes[pos] == "ː":
                pos += 1
        else:
            # Consonant with no following vowel at all (word-final cluster)
            if initial == "Ø":
                continue  # nothing to emit
            final = _STRAY_VOWEL.get(initial, "e")

        # Coda consonant(s)
        _append_er = False
        _append_ou = False
        _append_sv = ""  # "i" or "u" for semivowel vocalization
        _coda_kept: list[tuple[str, str, str]] = []  # (initial, final, tone)
        while pos < n:
            nxt = ipa_phonemes[pos]
            if nxt in _SKIP or unicodedata.category(nxt).startswith("M"):
                pos += 1
                continue
            if nxt == "ː":
                pos += 1
                continue
            if _is_vowel(nxt) or nxt in _PUNCTUATION_MAP:
                break

            # Rhotic coda (ɹ) — produces a separate 尔 (er) syllable
            # e.g., "are" → a + er, "star" → si-ta-er
            # But only if it's truly a coda (not onset of next syllable)
            if nxt in ("ɹ", "r"):
                peek = pos + 1
                while peek < n and (ipa_phonemes[peek] in _SKIP
                                    or unicodedata.category(ipa_phonemes[peek]).startswith("M")
                                    or ipa_phonemes[peek] == "ː"):
                    peek += 1
                if peek < n and _is_vowel(ipa_phonemes[peek]):
                    break  # r is onset of next syllable (e.g., "very")
                # Coda r — emit current syllable, then queue an er syllable
                pos += 1
                # Finish current syllable first (tone/emit happens below),
                # then append er. We use a flag.
                _append_er = True
                continue

            # Nasal coda — merge into final if it's truly a coda
            if nxt in _NASAL_CODAS:
                peek = pos + 1
                while peek < n and (ipa_phonemes[peek] in _SKIP
                                    or unicodedata.category(ipa_phonemes[peek]).startswith("M")
                                    or ipa_phonemes[peek] == "ː"):
                    peek += 1
                if peek < n and _is_vowel(ipa_phonemes[peek]):
                    break  # nasal is onset of next syllable, don't consume
                merged = _NASAL_CODAS[nxt].get(final)
                if merged:
                    final = merged
                    pos += 1
                    continue
                # Unmerged nasal (unusual) — fall through to stray handling

            # Lateral coda (l) — vocalize to ou (dark L ≈ [ʊ]).
            # "world" → wer-ou, "girl" → ger-ou, "milk" → mi-ou
            if nxt == "l":
                peek = pos + 1
                while peek < n and (ipa_phonemes[peek] in _SKIP
                                    or unicodedata.category(ipa_phonemes[peek]).startswith("M")
                                    or ipa_phonemes[peek] == "ː"):
                    peek += 1
                if peek < n and _is_vowel(ipa_phonemes[peek]):
                    break  # l is onset of next syllable (e.g., "hello")
                pos += 1
                _append_ou = True
                continue

            # Semivowel coda — vocalize: j→i, w→u
            if nxt in ("j", "w"):
                peek = pos + 1
                while peek < n and (ipa_phonemes[peek] in _SKIP
                                    or unicodedata.category(ipa_phonemes[peek]).startswith("M")
                                    or ipa_phonemes[peek] == "ː"):
                    peek += 1
                if peek < n and _is_vowel(ipa_phonemes[peek]):
                    break  # semivowel is onset of next syllable
                _append_sv = "i" if nxt == "j" else "u"
                pos += 1
                continue

            # Remaining coda consonants:
            #   stops  → always drop (Mandarin has no coda stops)
            #   sibilants → always keep (si5 ≈ syllabic s, weightless)
            #   others (f, h, …) → keep if stressed, drop if not
            peek = pos + 1
            while peek < n and (ipa_phonemes[peek] in _SKIP
                                or unicodedata.category(ipa_phonemes[peek]).startswith("M")
                                or ipa_phonemes[peek] == "ː"):
                peek += 1
            if peek < n and _is_vowel(ipa_phonemes[peek]):
                break  # consonant is onset of next syllable

            if nxt in _IPA_STOPS:
                # Stops: always drop
                pos += 1
                continue

            is_sibilant = nxt in _IPA_SIBILANTS
            if is_sibilant or is_primary or is_secondary:
                # Keep — emit as epenthesized syllable inline (don't
                # break out, which would lose the stress context).
                cons, pos = _match_consonant(ipa_phonemes, pos)
                if cons:
                    ev = _STRAY_VOWEL.get(cons, "e")
                    _coda_kept.append((cons, ev, "5"))
                continue
            # Unstressed, non-sibilant, non-stop coda — drop
            pos += 1
            continue

        # Unstressed schwa vowel selection depends on the initial:
        #   - t,d,k,g,l,n,s,z,r,c,sh,zh,ch → e  (特te,德de,克ke,格ge...)
        #   - b,p,m,f,w → u  (布bu,普pu,姆mu,夫fu — be/pe/fe invalid)
        #   - h,Ø → a  (哈ha,阿a — he=[xɤ] sounds wrong for schwa)
        # Stressed/secondary schwa always stays as a (fuller quality).
        if was_schwa and not is_primary and not is_secondary:
            _LABIALS = {"b", "p", "m", "f"}
            _KEEP_A = {"h", "Ø"}
            if initial in _LABIALS:
                _remap = "u"
            elif initial in _KEEP_A:
                _remap = "a"
            else:
                _remap = "e"
            if final == "a":
                final = _remap
            elif final.startswith("a") and final in ("an", "ang"):
                # Nasal-merged schwa: an→en/un, ang→eng/ong
                if _remap == "u":
                    final = "un" if final == "an" else "ong"
                elif _remap == "e":
                    final = "en" if final == "an" else "eng"

        # Mandarin palatalization: s→x, z→j, sh→x, zh→j, ch→q before
        # high-front finals (i, ia, ie, ian, in, iang, ing, etc.).
        # Only for real vowels — epenthetic si5/zi5/shi5 stay as-is
        # (they represent syllabic sibilants [sɿ], not true [si]).
        if is_real_vowel and initial in _PALATALIZE and final.startswith("i"):
            initial = _PALATALIZE[initial]

        # Tone based on stress.
        # Tone 5 (neutral/轻声) is naturally shorter in the model,
        # helping approximate English stress-timing from a syllable-timed
        # model.  Stressed syllables get full tones (4/2), unstressed get 5.
        if is_primary:
            tone = "4"
        elif is_secondary:
            tone = "2"
        else:
            tone = "5"

        result.extend([initial, final, tone])

        # Append vocalized / kept coda syllables
        if _append_er:
            result.extend(["Ø", "er", "5"])
        if _append_ou:
            result.extend(["Ø", "ou", "5"])
        if _append_sv:
            result.extend(["Ø", _append_sv, "5"])
        for c_init, c_fin, c_tone in _coda_kept:
            result.extend([c_init, c_fin, c_tone])

    return result


# ---------------------------------------------------------------------------
# High-level: English text → pinyin phoneme list
# ---------------------------------------------------------------------------

# Real punctuation that warrants a pause (pad token).  Spaces are
# deliberately excluded — padding after spaces creates choppy word
# boundaries.  Tones always get a pad (syllable boundary).
_PAD_AFTER: set[str] = {
    ".", ",", "!", "?", ":", ";",
    "—", "…", "。", "，", "？", "！", "：", "；", "、",
    "1", "2", "3", "4", "5",
}


def pinyin_to_ids(
    phonemes: list[str],
    phoneme_id_map: dict[str, list[int]],
) -> list[int]:
    """Convert pinyin phonemes to model IDs with English-tuned padding.

    Unlike the default ``phonemes_to_ids`` (which pads after every
    group-end token including spaces), this version only pads after
    tones and real punctuation.  Spaces are emitted without a following
    pad so that words within a phrase flow together.
    """
    bos = phoneme_id_map["^"]
    eos = phoneme_id_map["$"]
    pad = phoneme_id_map["_"]

    ids: list[int] = list(bos)
    for phoneme in phonemes:
        if phoneme not in phoneme_id_map:
            continue
        ids.extend(phoneme_id_map[phoneme])
        if phoneme in _PAD_AFTER:
            ids.extend(pad)
    ids.extend(eos)
    return ids


def english_to_pinyin_phonemes(
    text: str,
    espeak_data_dir: object = None,
) -> list[list[str]]:
    """Convert English text to pinyin phoneme lists.

    Returns list-of-lists matching the shape of
    ``ChinesePhonemizer.phonemize()`` so callers can feed the result
    directly into ``phonemes_to_ids()``.
    """
    from piper.phonemize_espeak import EspeakPhonemizer
    from piper.voice import PiperVoice

    data_dir = espeak_data_dir or PiperVoice.espeak_data_dir
    phonemizer = EspeakPhonemizer(data_dir)
    ipa_sentences = phonemizer.phonemize("en-us", text)

    result: list[list[str]] = []
    for ipa_phonemes in ipa_sentences:
        stressed: set[int] = set()
        secondary: set[int] = set()
        for i, ch in enumerate(ipa_phonemes):
            if ch == "ˈ" and i + 1 < len(ipa_phonemes):
                stressed.add(i + 1)
            elif ch == "ˌ" and i + 1 < len(ipa_phonemes):
                secondary.add(i + 1)
        pinyin = ipa_to_pinyin(ipa_phonemes, stressed, secondary)
        if pinyin:
            result.append(pinyin)

    return result
