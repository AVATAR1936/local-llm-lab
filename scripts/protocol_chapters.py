# -*- coding: utf-8 -*-
"""Rozdily protokolu za khodom pary: dva rivni z tajmkodamy.

Chomu tak (plan 1.3): struktura beretsya z samoyi pary, a ne z perelika
kategorij. Model' rozbyvaye stenohramu na rozdily (velyki temy) i
pidrozdily z punktamy; kod pereviryaye te, shcho mozhna pereviryty bez
chytannya: tajmkody spravzhni, jdut' po poryadku, i para pokryta bez velykykh
dirok. Mezhi bez donavchannya model' stavyt' neprecyzno (arXiv 2601.02128),
tomu stabil'nist' mezh mizh prohonamy mirayet'sya okremo.
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm

TS = re.compile(r"\[(\d\d:\d\d:\d\d)\]")

PROMPT = """Розбий стенограму заняття на розділи за ходом заняття. Пиши українською.

Два рівні:
- розділи - великі частини заняття (тема, блок матеріалу, організаційна частина);
- у кожному розділі - підрозділи, у кожного 2-5 коротких пунктів: що саме пояснено, показано, вирішено чи сказано.

Правила:
- start - таймкод початку, точно такий, як у квадратних дужках у стенограмі. Не вигадуй таймкодів.
- Розділи й підрозділи - у порядку заняття, без пропусків: кожна частина заняття має потрапити в якийсь підрозділ.
- Організаційні моменти (розклад, здача робіт, строки) - окремим підрозділом там, де вони прозвучали.
- Спирайся лише на стенограму. Нічого не додавай від себе.
- title - тема всього заняття одним рядком.

СТЕНОГРАМА:
"""

SCHEMA = {"type": "object", "required": ["title", "chapters"], "properties": {
    "title": {"type": "string"},
    "chapters": {"type": "array", "items": {"type": "object", "required": ["start", "title", "sections"],
        "properties": {"start": {"type": "string"}, "title": {"type": "string"},
                       "sections": {"type": "array", "items": {"type": "object",
                           "required": ["start", "title", "points"],
                           "properties": {"start": {"type": "string"}, "title": {"type": "string"},
                                          "points": {"type": "array", "items": {"type": "string"}}}}}}}}}}


def secs(ts):
    h, m, s = (int(x) for x in ts.split(":"))
    return h * 3600 + m * 60 + s


def body(transcript):
    """Stenohrama bez shapky fajlu (ryadky z #)."""
    return "\n".join(l for l in transcript.splitlines() if l.strip() and not l.startswith("#"))


def chapters(transcript, seed=42):
    r = llm.ask(PROMPT + body(transcript), seed=seed, predict=6000, fmt=SCHEMA)
    out = json.loads(r["response"])
    return out, {"out_tokens": r.get("eval_count"), "seconds": round(r.get("total_duration", 0) / 1e9, 1),
                 "prompt_tokens": r.get("prompt_eval_count")}


def check(transcript, out, gap_warn=15 * 60):
    """Te, shcho pereviryayet'sya kodom: spravzhni tajmkody, poryadok, pokryttya."""
    real = [secs(t) for t in TS.findall(body(transcript))]
    real_set, end = set(real), max(real) if real else 0
    starts, fake, order = [], [], True
    for ch in out["chapters"]:
        for sub in [ch] + ch["sections"]:
            t = sub["start"]
            if not re.fullmatch(r"\d\d:\d\d:\d\d", t) or secs(t) not in real_set:
                fake.append(t)
    subs = [secs(s["start"]) for ch in out["chapters"] for s in ch["sections"]
            if re.fullmatch(r"\d\d:\d\d:\d\d", s["start"])]
    order = subs == sorted(subs)
    gaps = [b - a for a, b in zip(subs, subs[1:])]
    head = subs[0] - (min(real) if real else 0) if subs else None
    tail = end - subs[-1] if subs else None
    return {"chapters": len(out["chapters"]), "sections": len(subs), "fake_ts": fake, "in_order": order,
            "max_gap_min": round(max(gaps) / 60, 1) if gaps else None,
            "gaps_over": [(f"{a // 60}:{a % 60:02d}", round(g / 60, 1)) for a, g in zip(subs, gaps) if g > gap_warn],
            "head_min": round(head / 60, 1) if head is not None else None,
            "tail_min": round(tail / 60, 1) if tail is not None else None,
            "duration_min": round(end / 60, 1)}


def boundary_agreement(a, b, tol=90):
    """Chastka pochatkiv rozdiliv prohonu a, dlya yakykh u prohoni b ye pochatok
    v mezhakh tol sekund (i navpaky) - F1 mizh dvoma rozbyttyamy."""
    A = [secs(c["start"]) for c in a["chapters"] if re.fullmatch(r"\d\d:\d\d:\d\d", c["start"])]
    B = [secs(c["start"]) for c in b["chapters"] if re.fullmatch(r"\d\d:\d\d:\d\d", c["start"])]
    if not A or not B:
        return 0.0
    p = sum(any(abs(x - y) <= tol for y in B) for x in A) / len(A)
    r = sum(any(abs(y - x) <= tol for x in A) for y in B) / len(B)
    return round(2 * p * r / (p + r), 2) if p + r else 0.0


def render_full(out):
    lines = [f"# {out['title']}", ""]
    for ch in out["chapters"]:
        lines.append(f"## [{ch['start']}] {ch['title']}")
        for s in ch["sections"]:
            lines.append(f"### [{s['start']}] {s['title']}")
            lines += [f"- {p}" for p in s["points"]]
        lines.append("")
    return "\n".join(lines)


# --- вікна по 5 хвилин: одиниці задає код, модель описує кожну ----------
# Перший варіант (модель розмічає всю пару сама) давав вигадані таймкоди і
# дірки до 29 хвилин. Тут покриття - за побудовою: кожне вікно має номер, і
# відповідь на кожен номер перевіряється.

WIN_PROMPT = """Нижче - стенограма заняття, розрізана на пронумеровані вікна по кілька хвилин. Пиши українською, без LaTeX: формули - звичайним текстом.
Для кожного вікна:
- subtitle: коротко, що саме в цьому вікні;
- points: 1-4 короткі пункти - що саме пояснено, показано, вирішено чи сказано в цьому вікні. Організаційні моменти (розклад, здача робіт, строки) - теж пунктами.
Спирайся лише на текст вікна. Нічого не додавай від себе. Рівно один елемент на кожен id.

ВІКНА:
"""

# Рішення "та сама тема чи нова" вікно за вікном модель тягне в "та сама":
# двічі поспіль уся пара ставала одним розділом, і уточнення масштабу теми в
# інструкції не допомогло. Тому розділи - окремим кроком, над усіма
# підзаголовками разом (group).
WIN_SCHEMA = {"type": "object", "required": ["windows"], "properties": {"windows": {"type": "array", "items": {
    "type": "object", "required": ["id", "subtitle", "points"],
    "properties": {"id": {"type": "integer"}, "subtitle": {"type": "string"},
                   "points": {"type": "array", "items": {"type": "string"}}}}}}}

GROUP_PROMPT = """Нижче - підзаголовки й пункти пронумерованих вікон одного заняття, по порядку.
Згрупуй вікна в частини заняття: частина - неперервний діапазон вікон однієї великої теми (блок матеріалу, організаційна частина, розбір задачі). Зазвичай за заняття 3-8 частин.
Для кожної частини: first і last - номери першого й останнього вікна, title - назва частини. Частини - по порядку, без пропусків і перетинів, від вікна 1 до останнього.
Назва частини - НЕ назва всього заняття чи дисципліни. Також дай title_all - тему всього заняття одним рядком.

ВІКНА:
"""

GROUP_SCHEMA = {"type": "object", "required": ["title_all", "parts"], "properties": {
    "title_all": {"type": "string"},
    "parts": {"type": "array", "items": {"type": "object", "required": ["first", "last", "title"],
              "properties": {"first": {"type": "integer"}, "last": {"type": "integer"},
                             "title": {"type": "string"}}}}}}
WIN_BATCH = 12       # вікон на виклик: година мови, з запасом у вікні моделі


def windows(transcript, size=300):
    """[{id, start, text}] - vikna po `size` sekund, rizani po mezhakh
    sehmentiv stenohramy (ryadok z tajmkodom), ne posered rechennya."""
    out, cur, t0 = [], [], None
    for line in body(transcript).splitlines():
        m = TS.match(line)
        if not m:
            if cur:
                cur.append(line)
            continue
        t = secs(m.group(1))
        if t0 is None or t - t0 >= size:
            if cur:
                out.append({"id": len(out) + 1, "start": ts0, "text": "\n".join(cur)})
            cur, t0, ts0 = [], t, m.group(1)
        cur.append(TS.sub("", line, count=1).strip())
    if cur:
        out.append({"id": len(out) + 1, "start": ts0, "text": "\n".join(cur)})
    return out


def describe(wins, seed=42, retries=2):
    got, stats = {}, {"calls": 0, "out_tokens": 0, "seconds": 0.0, "missing_after": []}
    todo = wins
    for _ in range(1 + retries):
        if not todo:
            break
        for k in range(0, len(todo), WIN_BATCH):
            part = todo[k:k + WIN_BATCH]
            text = "\n\n".join(f"[вікно {w['id']}] ({w['start']})\n{w['text']}" for w in part)
            r = llm.ask(WIN_PROMPT + text, seed=seed, predict=6000, fmt=WIN_SCHEMA)
            stats["calls"] += 1
            stats["out_tokens"] += r.get("eval_count", 0)
            stats["seconds"] += r.get("total_duration", 0) / 1e9
            try:
                items = json.loads(r["response"]).get("windows", [])
            except json.JSONDecodeError:
                continue
            ids = {w["id"] for w in part}
            for it in items:
                if it.get("id") in ids and it["id"] not in got:
                    got[it["id"]] = it
        todo = [w for w in wins if w["id"] not in got]
    stats["missing_after"] = [w["id"] for w in todo]
    stats["seconds"] = round(stats["seconds"], 1)
    return got, stats


def group(wins, got, seed=42):
    """Rozdily nad usima pidzaholovkamy razom. Vidpovid' remontuyet'sya kodom
    za pochatkamy chastyn: navit' kryvi diapazony dayut' rozbyttya bez dirok
    i peretyniv. Povertaye (title_all, [(first_id, title)], stats)."""
    text = "\n".join(f"[{w['id']}] ({w['start']}) {got.get(w['id'], {}).get('subtitle', '')}: "
                     + "; ".join(got.get(w["id"], {}).get("points", [])) for w in wins)
    r = llm.ask(GROUP_PROMPT + text, seed=seed, predict=2000, fmt=GROUP_SCHEMA)
    ans = json.loads(r["response"])
    n = len(wins)
    raw = sorted((p for p in ans.get("parts", []) if 1 <= p.get("first", 0) <= n), key=lambda p: p["first"])
    starts, seen = [], set()
    for p in raw:
        if p["first"] not in seen:
            seen.add(p["first"])
            starts.append((p["first"], p["title"]))
    if not starts or starts[0][0] != 1:
        starts.insert(0, (1, starts[0][1] if starts else "(без назви)"))
        starts = [s for i, s in enumerate(starts) if i == 0 or s[0] != 1]
    # Чи відповідь була правильною ще до ремонту - для заміру, не для роботи.
    exact = [(p["first"], p["last"]) for p in raw]
    valid = bool(exact) and exact[0][0] == 1 and exact[-1][1] == n and all(
        b[0] == a[1] + 1 for a, b in zip(exact, exact[1:]))
    stats = {"out_tokens": r.get("eval_count"), "seconds": round(r.get("total_duration", 0) / 1e9, 1),
             "valid_before_repair": valid}
    return ans.get("title_all", ""), starts, stats


def assemble(title, wins, got, starts):
    """Rozdily - z group(); pidrozdily - sami vikna."""
    first = dict(starts)
    chs = []
    for w in wins:
        g = got.get(w["id"], {"subtitle": "(без опису)", "points": []})
        if w["id"] in first or not chs:
            chs.append({"start": w["start"], "title": first.get(w["id"], ""), "sections": []})
        chs[-1]["sections"].append({"start": w["start"], "title": g["subtitle"], "points": g["points"]})
    return {"title": title, "chapters": chs}
