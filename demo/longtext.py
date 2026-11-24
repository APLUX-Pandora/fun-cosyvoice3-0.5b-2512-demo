"""Long text for the demo: split into segments (one LLM query + one token2wav stream each) and join their
audio into one stream.

Why: one segment must fit the converted shapes - LLM CL 1024 (sos + prompt + text + task + generated tokens; the prompt
is the voice's reference text + speech tokens, or an instruction) and DiT N <= 2 x (voice prompt speech tokens +
generated tokens). The DiT has buckets up to 2048, but a
streaming hop at N > 1536 runs the 2048 bin, which is slower than real time, and playback stalls, so the budget is
N <= 1536. Every segment uses the same voice prompt (as the model's reference implementation does), so the voice
does not drift.

Segments: each paragraph (newline separated) goes through the SDK text frontend (normalization + split,
60-80 text tokens per segment); a segment whose estimated speech tokens exceed the budget is re-split at sentence
ends, a sentence that is still too long at ；：，、;:,, a run without punctuation is cut hard (between words for
space-separated scripts). Length unit (`units`): about one syllable in every language of the model. Estimate: speech
tokens per unit of the voice's own prompt (prompt speech tokens / prompt units) x MARGIN (MARGIN_INSTRUCT with an
instruction: speed and style instructions change the rate, e.g. "as slowly as possible" ~1.4x).
Joining: leading / trailing silence (relative to the segment's loudness for quiet voices) at the joints is trimmed to
PAD_S and a fixed pause inserted by how the segment ended (sentence / paragraph / comma / hard cut). Speech is
emitted as soon as it arrives; only the silence after it is held back until the next audio (it may be the segment's
trailing silence).
"""
import re

import numpy as np

SR = 24000
CL, N_MAX_STREAM, N_HARD = 1024, 1536, 2048
MARGIN = 1.3                          # estimate x margin must fit the budget
MARGIN_INSTRUCT = 2.0
PAUSE_S = {"para": 0.6, "sent": 0.3, "comma": 0.15, "hard": 0.0}
PAD_S, SIL_DB, WIN_S = 0.05, -45.0, 0.02
# silence = 20 ms windows below SIL_DB; for a quiet voice (the segment's loudest window so far below QUIET_PEAK_DB, e.g.
# a clone of a quiet recording whose speech is around -50 dBFS) below that window - SIL_REL_DB, floored at SIL_FLOOR_DB
# (digital silence stays silence). The built-in voices peak at -21..-5 dBFS per segment and keep the fixed threshold.
QUIET_PEAK_DB, SIL_REL_DB, SIL_FLOOR_DB = -25.0, 30.0, -65.0

CJK = r"一-鿿㐀-䶿"
SYLLABIC = CJK + r"぀-ゟ゠-ヿ가-힣"       # one unit per character: CJK, hiragana, katakana, Hangul syllables
LETTERS = r"A-Za-zÀ-ÖØ-öø-ɏͰ-ϿЀ-ӿ"         # Latin (with accents), Greek, Cyrillic
WORD = re.compile(rf"[{LETTERS}]+(?:['’][{LETTERS}]+)*")
VOWELS = re.compile(r"[aeiouyàáâãäåæèéêëìíîïòóôõöøœùúûüýÿāăąēėęěīįōőūůűųаеёиоуыэюяαεηιουωάέήίόύώ]+")
SENT_END = "。！？!?…"
SOFT = "；：，、;:,"
CLOSE = "”’」』）》】)\"'"


def _word_units(w):
    if w.isupper() and len(w) <= 5:                              # acronym, read letter by letter
        return len(w)
    return max(1, len(VOWELS.findall(w.lower())))


def units(s):
    """speech units of a normalized text, about one syllable each, for any of the model's languages: one per CJK
    character, kana or Hangul syllable, the estimated syllables (vowel groups) of each Latin / Cyrillic / Greek word"""
    return len(re.findall(f"[{SYLLABIC}]", s)) + sum(_word_units(w) for w in WORD.findall(s))


class Budget:
    """segment budget of a voice (voice pack: prompt speech tokens, prompt text) and LLM prompt (llm_rows: the voice's
    prompt text + speech tokens, or an instruction)"""

    def __init__(self, voice_meta, n_prompt_tok, llm_rows, margin=MARGIN):
        self.P, self.R = n_prompt_tok, llm_rows
        self.rate = n_prompt_tok / max(units(voice_meta["prompt_text"]), 1)      # speech tokens per unit
        self.max_gen = min(N_MAX_STREAM // 2 - self.P, CL - 8 - self.R - 80)    # 80: text tokens of a segment
        self.max_units = int(self.max_gen / (self.rate * margin))
        if self.max_units < 1:
            raise ValueError("the voice's prompt leaves no room for text (reference recording or transcript too long)")

    def est(self, text):
        return self.rate * units(text)

    def max_tokens(self, n_text_tok):
        """hard cap of generated tokens for one query: LLM context and the largest DiT bucket"""
        return int(min(CL - 4 - self.R - n_text_tok, N_HARD // 2 - self.P))


def _sentences(p):
    """sentences ending with 。！？!?… or with "." followed by a space / the end (not inside a number)"""
    body = rf"(?:[^{SENT_END}.]|\.(?=\S))"                    # a character that does not end a sentence
    out = re.findall(rf"{body}*(?:[{SENT_END}]+|\.+)[{re.escape(CLOSE)}]*|{body}+$", p)
    return [s for s in out if s.strip()]


def _pieces(s, limit):
    """a sentence of more than `limit` units -> pieces <= limit: at soft punctuation, else hard cut"""
    if units(s) <= limit:
        return [s]
    parts = re.findall(rf"[^{SOFT}]*[{SOFT}]+|[^{SOFT}]+$", s)
    out, cur = [], ""
    for part in parts:
        if cur and units(cur + part) > limit:
            out.append(cur)
            cur = ""
        while units(part) > limit:                               # no punctuation at all: hard cut
            k = 1
            while k < len(part) and units(part[:k + 1]) <= limit:
                k += 1
            sp = part.rfind(" ", 0, k)
            if sp > 0 and not re.search(f"[{SYLLABIC}]", part[sp:k]):   # between words for space-separated scripts
                k = sp + 1
            out.append(part[:k])
            part = part[k:]
        cur += part
    if cur:
        out.append(cur)
    return out


def _kind(t):
    t = t.rstrip("".join(CLOSE) + " ")
    if not t:
        return "hard"
    return "sent" if t[-1] in SENT_END + "." else ("comma" if t[-1] in SOFT else "hard")


def split_text(text, fe, budget):
    """-> list of {"text", "ids", "units", "est", "end", "pause"} (normalized segment texts, token ids)."""
    segs = []
    for para in [p.strip() for p in re.split(r"\n+", str(text)) if p.strip()]:
        psegs = []
        for seg in fe.normalize(para, split=True):              # SDK normalization and segmentation
            if units(seg) <= budget.max_units:
                psegs.append(seg)
                continue
            k = -(-units(seg) // budget.max_units)   # balanced: k pieces of ~equal size, not greedy + short tail
            lim = min(budget.max_units, int(units(seg) / k * 1.15) + 1)
            cur = ""
            for s in _sentences(seg):
                for piece in _pieces(s, budget.max_units):     # a sentence is cut only if it alone is over budget
                    if cur and units(cur + piece) > lim:
                        psegs.append(cur)
                        cur = ""
                    cur += piece
            if cur:
                psegs.append(cur)
        for i, t in enumerate(psegs):
            end = "para" if i == len(psegs) - 1 else _kind(t)
            if end == "hard" and t.rstrip()[-1:] not in tuple(SENT_END + SOFT + "."):
                t = t.rstrip() + ("，" if re.search(f"[{SYLLABIC}]", t) else ",")   # a hard cut ends like a comma
            segs.append({"text": t, "end": end})
    for s in segs:
        s["ids"] = fe.encode(s["text"])
        s["units"] = units(s["text"])
        s["est"] = round(budget.est(s["text"]), 1)
        s["pause"] = PAUSE_S.get(s["end"], 0.3)
    if segs:
        segs[-1]["pause"] = 0.0
    return segs


class Joiner:
    """Turns the per-segment chunk streams into one stream: trims segment edges, inserts the pauses."""

    def __init__(self, sr=SR):
        self.sr, self.win = sr, int(WIN_S * sr)
        self.pad = int(PAD_S * sr)
        self.held = np.zeros(0, np.float32)
        self.tail = False                       # held = the silence right after emitted speech (end keeps PAD_S of it)
        self.lead = False
        self.spoke = False
        self.peak = -np.inf                     # loudest window of the current segment so far (dBFS)

    def _speech(self, w):
        n = len(w) // self.win
        if n == 0:
            return np.zeros(0, bool)
        db = 20 * np.log10(np.sqrt((w[: n * self.win].reshape(n, self.win) ** 2).mean(1) + 1e-12))
        self.peak = max(self.peak, float(db.max()))
        thr = SIL_DB if self.peak >= QUIET_PEAK_DB else max(SIL_FLOOR_DB, self.peak - SIL_REL_DB)
        return db > thr

    def begin(self, trim_lead):
        self.lead = trim_lead
        self.spoke = False
        self.peak = -np.inf

    def push(self, wav):
        """-> list of float32 arrays to emit now"""
        tail = self.tail and len(self.held) > 0
        w = np.concatenate([self.held, np.asarray(wav, np.float32)])
        self.held, self.tail = np.zeros(0, np.float32), False
        if self.lead:
            m = self._speech(w)
            if not m.any():
                return []
            on = max(0, int(np.argmax(m)) * self.win - self.pad)
            w = _fade(w[on:], self.sr, fade_in=True) if on else w
            self.lead = False
        m = self._speech(w)
        self.spoke = self.spoke or bool(m.any())
        if self.spoke and len(m) and not m[-int(0.3 / WIN_S):].any():   # speech, then >= 0.3 s silence: maybe the tail
            # emit the speech now and hold back only the silence after it (a streaming chunk is seconds long): if the
            # segment ends here, end() trims it; if more speech follows, it is emitted with that speech
            if m.any():
                cut = (len(m) - int(np.argmax(m[::-1]))) * self.win
                self.held, self.tail = w[cut:], True
                return [w[:cut]]
            self.held, self.tail = w, tail
            return []
        return [w]

    def end(self, pause_s):
        """segment finished: trim its trailing silence, append the pause"""
        w, self.held = self.held, np.zeros(0, np.float32)
        tail, self.tail = self.tail, False
        m = self._speech(w)
        if len(m) and m.any():
            off = min(len(w), (len(m) - int(np.argmax(m[::-1]))) * self.win + self.pad)
            w = _fade(w[:off], self.sr, fade_in=False)
        elif len(w) and tail:                                    # the silence after the last speech: keep PAD_S
            w = _fade(w[:min(len(w), self.pad)], self.sr, fade_in=False)
        elif len(w):
            w = w[:0]
        out = [w] if len(w) else []
        if pause_s > 0:
            out.append(np.zeros(int(pause_s * self.sr), np.float32))
        return out


def _fade(w, sr, fade_in, ms=10):
    n = min(len(w), int(sr * ms / 1000))
    if n:
        w = w.copy()
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        if fade_in:
            w[:n] *= ramp
        else:
            w[-n:] *= ramp[::-1]
    return w
