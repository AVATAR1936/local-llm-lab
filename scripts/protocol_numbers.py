# -*- coding: utf-8 -*-
"""Rozdil "Pravyla i cyfry": chysla znakhodyt' kod, model' lyshe poyasnyuye.

Chomu tak (0.11, plan): u odnomu prokhodi model' bachyt' usi chysla, ale
pry vidbori v odyn spysok vykydaye umovni j porohovi. Tut vidbir ne mozhe
zahubyty chyslo movchky: kozhne rechennya z chyslom maye nomer, i vidpovid'
na kozhen nomer perevirayet'sya kodom.

Kroky:
  1. mentions() - kozhne rechennya stenohramy, de ye chyslo cyframy abo
     slovom, z tajmkodom i poperednim rechennyam dlya kontekstu;
  2. classify() - model' kazhe pro kozhne: pravylo kursu chy fon, i shcho
     same stverdzhuye (odnym ryadkom, chysla - yak u rechenni);
  3. section() - rozdil iz pravyl, z tajmkodamy.
"""
import collections, json, re, urllib.request

# Кількісні числівники словом. Порядкові ("перша атестація") навмисно ні:
# вони дають "по-перше", "на першому курсі" і майже не несуть правил.
_WORDS = (r"один|одна|одне|одного|одну|одній|два|дві|двох|двом|три|трьох|трьом|чотири|чотирьох|"
          r"п'ять|п'яти|шість|шести|сім|семи|вісім|восьми|дев'ять|дев'яти|десять|десяти|"
          r"одинадцять|дванадцять|тринадцять|чотирнадцять|п'ятнадцять|шістнадцять|сімнадцять|"
          r"вісімнадцять|дев'ятнадцять|двадцять|тридцять|сорок|п'ятдесят|шістдесят|сімдесят|"
          r"вісімдесят|дев'яносто|сто|двісті|триста|тисяча|тисячі|тисяч|півтора|півтори|половина|половини")
NUM = re.compile(r"(?<![\w'])(?:\d+(?:[.,:]\d+)?(?:\s*[-–]\s*\d+(?:[.,:]\d+)?)?%?|(?:" + _WORDS + r"))(?![\w'])",
                 re.I)
TS = re.compile(r"\[(\d\d:\d\d:\d\d)\]")
SENT = re.compile(r"(?<=[.!?…])\s+")


def _norm_apos(t):
    return t.replace("’", "'").replace("ʼ", "'")


def mentions(transcript):
    """[{id, ts, text, prev}] - rechennya z chyslamy. Shapka fajlu (rядky z #)
    - ne stenohrama: tam model' rozpiznavannya i chas obrobky."""
    lines = [l for l in _norm_apos(transcript).splitlines() if l.strip() and not l.startswith("#")]
    sents = []           # (ts, sentence)
    ts = "00:00:00"
    for line in lines:
        for part in TS.split(line):
            if TS.fullmatch(f"[{part}]"):
                ts = part
                continue
            for s in SENT.split(part.strip()):
                if s:
                    sents.append((ts, s.strip()))
    out = []
    for i, (ts, s) in enumerate(sents):
        if NUM.search(s):
            out.append({"id": len(out) + 1, "ts": ts, "text": s,
                        "prev": sents[i - 1][1] if i else ""})
    return out


MODEL = "gemma4:12b"
OPTIONS = {"num_ctx": 32768, "temperature": 0.2, "top_p": 0.9, "top_k": 40,
           "repeat_penalty": 1.0, "num_predict": 6000}

CLASSIFY_PROMPT = """Нижче - пронумеровані речення зі стенограми лекції. У кожному є число (цифрами або словом).
Розклади їх на два списки:
- rules - речення, де число стосується правил цього курсу: бали й оцінювання, строки й дати, кількість робіт чи тестів, умови атестацій і заліку, перездачі, тривалість семестру, статистика оцінок у цьому курсі, обсяг завдань.
  Для кожного - id і fact: одне коротке твердження українською, що саме сказано, з числами точно як у реченні. Не округлюй, не обчислюй, не додавай того, чого немає в реченні. Контекст (попереднє речення) - лише щоб зрозуміти, до чого число.
- background - номери всіх інших речень: скільки людей на занятті, номери аудиторій, роки й події з історії, опитування, новини, приклади й обчислення з матеріалу лекції, а також коли слово-числівник не означає кількість ("один з варіантів").

Кожен id - рівно в одному зі списків.

РЕЧЕННЯ:
"""

# "Фон" - лише номер: ~2 токени замість ~15 на повний запис. На математичній
# парі 461 речення з числами, і повні записи не влазили в ліміт відповіді.
SCHEMA = {"type": "object", "required": ["background", "rules"], "properties": {
    "background": {"type": "array", "items": {"type": "integer"}},
    "rules": {"type": "array", "items": {"type": "object", "required": ["id", "fact"],
              "properties": {"id": {"type": "integer"}, "fact": {"type": "string"}}}}}}
BATCH = 120          # речень на виклик: довга пара не впирається в ліміт у принципі


def _ask(prompt, seed):
    body = {"model": MODEL, "prompt": prompt, "stream": False, "think": False, "format": SCHEMA,
            "options": {**OPTIONS, "seed": seed}}
    req = urllib.request.Request("http://localhost:11434/api/generate",
                                 data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    return json.load(urllib.request.urlopen(req, timeout=1800))


def _render(items):
    return "\n".join(f"[{m['id']}] ({m['ts']}) Контекст: {m['prev'] or '-'}\n    Речення: {m['text']}"
                     for m in items)


def classify(ms, seed=42, retries=2):
    """{id: {kind, fact}}. Vidpovid' na kozhen id perevirayet'sya; propushcheni
    pereprytuyut'sya okremo - movchky zahubytysya nichoho ne mozhe."""
    got, stats = {}, {"calls": 0, "out_tokens": 0, "seconds": 0.0, "missing_after": [], "truncated": 0}
    todo = ms
    for _ in range(1 + retries):
        if not todo:
            break
        for k in range(0, len(todo), BATCH):
            part = todo[k:k + BATCH]
            r = _ask(CLASSIFY_PROMPT + _render(part), seed)
            stats["calls"] += 1
            stats["out_tokens"] += r.get("eval_count", 0)
            stats["seconds"] += r.get("total_duration", 0) / 1e9
            try:
                ans = json.loads(r["response"])
            except json.JSONDecodeError:
                # Обрізана відповідь: уся пачка піде на повтор, а не в тишу.
                stats["truncated"] += 1
                continue
            ids = {m["id"] for m in part}
            for it in ans.get("rules", []):
                if it.get("id") in ids and it["id"] not in got:
                    got[it["id"]] = {"kind": "правило", "fact": it.get("fact", "").strip()}
            for i in ans.get("background", []):
                if i in ids and i not in got:
                    got[i] = {"kind": "фон", "fact": ""}
        todo = [m for m in todo if m["id"] not in got]
    stats["missing_after"] = [m["id"] for m in todo]
    return got, stats


def lost_digits(sentence, fact):
    """Chysla rechennya, yakykh brakuye u formulyuvanni - z urakhuvannyam
    kil'kosti vkhodzhen': "7 laboratornykh, 6 i 7 neobov'yazkovi" -> "laby 6 i 7
    neobov'yazkovi" vtrachaye same druhu simku, i mnozhyna ts'oho ne pobachyt'."""
    have = collections.Counter(re.findall(r"\d+", fact))
    return list((collections.Counter(re.findall(r"\d+", sentence)) - have).elements())


def section(ms, got):
    """Rozdil iz pravyl u poryadku prozvuchannya, z tajmkodamy - kozhne chyslo
    mozhna pereviryty v zapysi. Yakshcho formulyuvannya zahubylo chyslo z
    rechennya, do ryadka dodayet'sya dosliva cytata: zahubyty movchky ne mozhna."""
    rows = []
    for m in ms:
        g = got.get(m["id"])
        if not g or g["kind"] != "правило" or not g["fact"]:
            continue
        row = f"- [{m['ts']}] {g['fact']}"
        if lost_digits(m["text"], g["fact"]):
            row += f" — дослівно: «{m['text']}»"
        rows.append(row)
    return "\n".join(rows) if rows else "немає"
