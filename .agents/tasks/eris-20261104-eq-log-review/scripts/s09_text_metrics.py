#!/usr/bin/env python
"""s09: so lieu van ban ve loi Eris (do dai, cau hoi cuoi, dinh dang, mo/ket, hoi do dong co...).

DAU VAO  : <joined_dir>/*.json (s03; chua transcript => nam trong TEMP)
DAU RA   : JSON tong hop (khong chua noi dung hoi thoai ngoai cac cum tu mo/ket NGAN va chung)
           ghi vao duong dan <out_json> (duoc phep dat trong thu muc task).

Chay:
    python -X utf8 s09_text_metrics.py <joined_dir> <out_json>

Pham vi (theo ngay bat dau session, UTC+7):
  A = 2026-11-01..2026-11-03   (pham vi chinh)
  B = 2026-10-24..2026-10-31   (mau thang 10 de so xu huong)
Moi "phat ngon" = 1 Root move (kind=move) co text hien thi (Surface.text, neu khong co thi Root.say).
Kenh = user_turn (tra loi user) | proactive (opening/autonomous/continuation) | tutor (tutor_result).
Ghi chu: day la heuristic regex (neu ro trong bao cao); khong thay the cham tay.
"""
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

SCOPES = {"A_2026-11-01..03": ("20261101", "20261103"), "B_2026-10-24..31": ("20261024", "20261031")}

Q_END = re.compile(r"\?\s*[\"'”’)]*\s*$")
HAS_Q = re.compile(r"\?")
LIST_LINE = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)", re.M)
HEADING = re.compile(r"^\s*#{1,6}\s+", re.M)
BOLD = re.compile(r"\*\*[^*]+\*\*")
LATEX = re.compile(r"\\\(|\\\[|\$\$")
OFFER_END = re.compile(
    r"(muốn\s+(tôi|em)\b[^.?!]*\?|cần\s+(tôi|em)\b[^.?!]*\?|để\s+(tôi|em)\s+[^.?!]*(không|nhé|nha)\??\s*$|"
    r"nói\s+(tôi|em)\s+(biết|nghe)|kể\s+(tôi|em)\s+nghe|có\s+muốn\s+(tôi|em))", re.I)
# hoi do dong co / nghi ngo y dinh nguoi dung (heuristic)
MOTIVE = re.compile(
    r"(anh|bạn|ông|cậu)\s+(đang|định|muốn)\s+(thử|đố|trêu|test|xem|dò|kiểm tra|bắt|dẫn|đợi|chờ|ngồi đợi)|"
    r"(thử|xem)\s+(xem\s+)?(tôi|em)\s+(có|dám)|"
    r"(đố mẹo|chơi chữ|tiện miệng trêu|thật hay|có thật|hay là)[^?]{0,80}\?|"
    r"(anh|bạn)\s+(hỏi|nói)\s+(kiểu\s+đó|thế)\s+(thì\s+)?(tôi\s+)?nghi|"
    r"(link|clip|bằng chứng)", re.I)
MA_NAY = re.compile(r"^\s*(Mà\s+(này|khoan|nghĩ lại|nói|thôi)|Nói\s+nốt|Còn\s+một\s+chỗ|Thêm\s+một)", re.I)
VI_CHARS = re.compile(r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", re.I)
JA_CHARS = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
SECOND_PERSON = [("anh", re.compile(r"\banh\b", re.I)), ("bạn", re.compile(r"\bbạn\b", re.I)),
                 ("em", re.compile(r"\bem\b", re.I)), ("mày", re.compile(r"\bmày\b", re.I))]


def words(s):
    return len(re.findall(r"\w+", s, flags=re.UNICODE))


def pctl(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    return round(s[max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))], 1)


def summarize(vals):
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "mean": round(statistics.mean(vals), 1), "median": pctl(vals, 0.5),
            "p90": pctl(vals, 0.9), "max": max(vals)}


def first_k(s, k):
    toks = re.findall(r"\w+|[^\w\s]", s.strip(), flags=re.UNICODE)
    return " ".join(toks[:k]).lower()


def last_clause(s):
    s = s.strip()
    parts = re.split(r"(?<=[.!?…])\s+", s)
    return parts[-1] if parts else s


def analyze(items):
    """items: list of dict(text, user_text|None, kind)"""
    out = {}
    texts = [i["text"] for i in items]
    n = len(texts)
    out["n"] = n
    ch = [len(t) for t in texts]
    wd = [words(t) for t in texts]
    out["chars"] = summarize(ch)
    out["words"] = summarize(wd)
    out["share_words_ge_60"] = round(sum(1 for w in wd if w >= 60) / n, 3) if n else None
    out["share_words_ge_100"] = round(sum(1 for w in wd if w >= 100) / n, 3) if n else None
    out["ends_with_question"] = sum(1 for t in texts if Q_END.search(t.strip()))
    out["has_question_mark"] = sum(1 for t in texts if HAS_Q.search(t))
    out["questions_ge_2"] = sum(1 for t in texts if len(HAS_Q.findall(t)) >= 2)
    out["offer_or_invite_end"] = sum(1 for t in texts if OFFER_END.search(last_clause(t)))
    out["list_lines"] = sum(1 for t in texts if LIST_LINE.search(t))
    out["headings"] = sum(1 for t in texts if HEADING.search(t))
    out["bold"] = sum(1 for t in texts if BOLD.search(t))
    out["latex"] = sum(1 for t in texts if LATEX.search(t))
    out["multi_paragraph"] = sum(1 for t in texts if "\n\n" in t.strip())
    out["motive_probe"] = sum(1 for t in texts if MOTIVE.search(t))
    out["ma_nay_opening"] = sum(1 for t in texts if MA_NAY.search(t))
    out["contains_ma_nay_anywhere"] = sum(1 for t in texts if re.search(r"\bMà này\b", t))
    out["japanese_chars_in_display"] = sum(1 for t in texts if JA_CHARS.search(t))
    out["no_vietnamese_diacritics"] = sum(1 for t in texts if len(t) > 20 and not VI_CHARS.search(t))
    sp = Counter()
    for t in texts:
        found = [name for name, rx in SECOND_PERSON if rx.search(t)]
        sp[("+".join(found) or "none")] += 1
    out["second_person_forms"] = dict(sp.most_common())
    op2 = Counter(first_k(t, 2) for t in texts)
    op3 = Counter(first_k(t, 3) for t in texts)
    out["top_openings_2w"] = op2.most_common(8)
    out["top_openings_3w"] = [(k, v) for k, v in op3.most_common(8) if v > 1]
    ed = Counter(" ".join(re.findall(r"\w+", last_clause(t).lower())[:3]) for t in texts)
    out["top_last_clause_starts_3w"] = [(k, v) for k, v in ed.most_common(8) if v > 1]
    # ty le do dai tra loi / do dai user (chi voi luot user)
    ratios_c, ratios_w = [], []
    for i in items:
        if i.get("user_text"):
            u = i["user_text"]
            if len(u) > 0:
                ratios_c.append(len(i["text"]) / max(1, len(u)))
                ratios_w.append(words(i["text"]) / max(1, words(u)))
    out["reply_to_user_len_ratio_words"] = summarize([round(x, 1) for x in ratios_w])
    out["share_reply_ge_5x_user_words"] = round(sum(1 for x in ratios_w if x >= 5) / len(ratios_w), 3) if ratios_w else None
    out["share_reply_ge_10x_user_words"] = round(sum(1 for x in ratios_w if x >= 10) / len(ratios_w), 3) if ratios_w else None
    uw = [words(i["user_text"]) for i in items if i.get("user_text")]
    out["user_words"] = summarize(uw)
    return out


def main():
    joined, out_json = Path(sys.argv[1]), Path(sys.argv[2])
    res = {"definition": {
        "utterance": "Root move (kind=move) voi text hien thi = Surface.text neu co, neu khong Root.say",
        "kinds": "user_reply | proactive (opening/autonomous/continuation) | tutor",
        "regex_note": "motive_probe, offer_or_invite_end, ma_nay_opening la heuristic regex; xem bao cao muc 'Gioi han'",
    }, "scopes": {}}
    for scope, (lo, hi) in SCOPES.items():
        by_kind = {"user_reply": [], "proactive": [], "tutor": []}
        sess_n = 0
        decisions = Counter()
        for p in sorted(joined.glob("2026*.json")):
            sid = p.stem
            if not (lo <= sid[:8] <= hi):
                continue
            d = json.loads(p.read_text("utf-8"))
            sess_n += 1
            prev_user = None
            for t in d["turns"]:
                if not t["final"]:
                    continue
                k = t["event_kind"]
                decisions[(k, t["resp_kind"], t.get("outcome") or "-")] += 1
                if t["resp_kind"] not in ("move", "prose_recovery"):
                    continue
                txt = t.get("surface_text") or t.get("say")
                if not txt:
                    continue
                if k == "user_turn":
                    by_kind["user_reply"].append({"text": txt, "user_text": t.get("user_text") or "", "session": sid})
                elif k == "tutor_result":
                    by_kind["tutor"].append({"text": txt, "session": sid})
                else:
                    by_kind["proactive"].append({"text": txt, "session": sid, "event_kind": k})
        sc = {"sessions": sess_n}
        for kname, items in by_kind.items():
            sc[kname] = analyze(items)
        sc["decision_counts"] = {"|".join(k): v for k, v in sorted(decisions.items(), key=lambda kv: -kv[1])}
        # no_reply ratio
        res["scopes"][scope] = sc
    out_json.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print("ok")


if __name__ == "__main__":
    main()
