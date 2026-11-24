"""Japanese input: the model reads kanji words unreliably (often with a Chinese-like reading) but reads
katakana well; the model's own Japanese example is written as katakana words separated by spaces. A Japanese paragraph
(one that contains kana) is therefore rewritten as that reading before synthesis:
  1. numbers -> kanji numerals (30万 -> 三十万, 3.5 -> 三点五, 71% -> 七十一パーセント), so that step 2 reads them
  2. words and their katakana reading from MeCab (fugashi + unidic-lite); the particles は / へ written as pronounced
     (ワ / エ); punctuation kept, attached to the word before it; words in Latin letters kept as they are.
The text normalization of the other languages is not applied to such paragraphs: it would send kana-only text to the English
normalizer (which reads numbers in English and fails on some inputs).
"""
import re
import unicodedata

KANA = re.compile(r"[぀-ゟ゠-ヿ]")
DIGITS = "〇一二三四五六七八九"
PUNCT = set("。、！？「」『』（）〈〉《》【】・…ー〜,.!?;:；：")
_reader = None


def is_japanese(text):
    return KANA.search(text) is not None


def _under_10000(n):
    s = ""
    for v, u in ((1000, "千"), (100, "百"), (10, "十")):
        d, n = divmod(n, v)
        if d:
            s += ("" if d == 1 else DIGITS[d]) + u
    return s + (DIGITS[n] if n else "")


def int_kanji(n):
    if n == 0:
        return "零"
    out = ""
    for v, u in ((10 ** 12, "兆"), (10 ** 8, "億"), (10 ** 4, "万")):
        d, n = divmod(n, v)
        if d:
            out += _under_10000(d) + u
    return out + (_under_10000(n) if n else "")


def numbers(text):
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)

    def rep(m):
        i, f, pct = m.group(1), m.group(2), m.group(3)
        s = int_kanji(int(i)) if len(i) <= 16 else "".join(DIGITS[int(c)] for c in i)
        if f:
            s += "点" + "".join(DIGITS[int(c)] for c in f)
        return s + ("パーセント" if pct else "")
    return re.sub(r"(\d+)(?:\.(\d+))?(%)?", rep, text)


def _make_reader():
    import fugashi
    tagger = fugashi.Tagger()

    def mecab(text):
        out = []
        for w in tagger(text):
            f = w.feature
            particle = f.pos1 == "助詞" and w.surface in ("は", "へ")
            out.append((w.surface, {"は": "ワ", "へ": "エ"}[w.surface] if particle else (f.kana or "")))
        return out
    return mecab


def reading(text):
    """Japanese text -> katakana words separated by spaces"""
    global _reader
    if _reader is None:
        _reader = _make_reader()
    text = numbers(unicodedata.normalize("NFKC", text))
    words = []
    for o, k in _reader(text):
        if not o.strip():
            continue
        if re.fullmatch(r"[A-Za-z0-9'’\- ]+", o) or not k.strip():
            k = o.strip()
        k = k.strip()
        if words and all(c in PUNCT for c in k):
            words[-1] += k
        else:
            words.append(k)
    return " ".join(w for w in words if w)
