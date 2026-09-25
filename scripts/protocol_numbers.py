# -*- coding: utf-8 -*-
"""Rozdil "Pravyla i cyfry": chysla znakhodyt' kod, model' lyshe poyasnyuye.

Chomu tak (0.11, plan): u odnomu prokhodi model' bachyt' usi chysla, ale
pry vidbori v odyn spysok vykydaye umovni j porohovi. Tut vidbir ne mozhe
zahubyty chyslo movchky: kozhne rechennya z chyslom maye nomer, i vidpovid'
na kozhen nomer perevirayet'sya kodom.

Kroky:
  1. mentions() - kozhne rechennya stenohramy, de ye chyslo (cyframy abo
     slovom) abo oznaka diyi chy stroku, z tajmkodom i poperednim rechennyam;
  2. classify() - dva nezalezhni prokhody odnym i tym samym naborom:
     RULES_PROMPT pro pravyla kursu (lyshe rechennya z chyslamy) i
     TASKS_PROMPT pro diyi j stroky (lyshe rechennya z oznakoyu diyi);
  3. section() - odyn spysok "Vazhlyve" z oboh prokhodiv, z tajmkodamy.

Chomu dva prokhody, a ne odyn (zamir 2026-09-25): odyn spil'nyj vopros
"vazhlyve chy fon" dav 4-5/14 na druhij lekciyi zamist' 12-13/14 - slovo
"vazhlyve" nichoho ne vymiryaye, i model' vyrishuye zanovo kozhnoho razu.
RULES_PROMPT tut - dosivno tej, shcho dav 23/23 i 12-13/14.
"""
import collections, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm

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

# Ознаки дії чи строку - для завдань без чисел ("надсилайте перелік групи",
# "запишіться в електронну чергу"). Наказовий спосіб множини - за закінченням;
# сміття на кшталт "треба розуміти" відсіює модель як фон.
TASK = re.compile(r"(?<![\w'])(?:\w+(?:айте|яйте|уйте|юйте|ійте|іть|іте)(?:ся|сь)?|\w+(?:ітьс|іться|йтесь|йтеся)|"
                  r"дедлайн\w*|домашн\w*|завданн\w*|треба|потрібно|необхідно|мусите|маєте|повинн\w*|"
                  r"обов'язков\w*|завчасно|заздалегідь|до\s+(?:понеділ|вівтор|серед|четвер|п'ятниц|субот|неділ|"
                  r"наступн|кінц)\w*)(?![\w'])", re.I)


def _norm_apos(t):
    return t.replace("’", "'").replace("ʼ", "'")


def _secs(ts):
    h, m, s = (int(x) for x in ts.split(":"))
    return h * 3600 + m * 60 + s


def within(ms, ranges):
    """Kandydaty, tajmkod yakykh potrapyv u odyn z vidrizkiv. Id ne
    perenumerovuyut'sya: etalon tochnosti trymayet'sya za tajmkod i tekst."""
    return [m for m in ms if any(a <= _secs(m["ts"]) < b for a, b in ranges)]


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
        num, task = bool(NUM.search(s)), bool(TASK.search(s))
        if num or task:
            out.append({"id": len(out) + 1, "ts": ts, "text": s,
                        "prev": sents[i - 1][1] if i else "",
                        "num": num, "task": task})
    return out



# Прохід 1. Дослівно той промпт, на якому зміряно 23/23 (лекція 1) і 12-13/14
# (лекція 2). Не правити без нового заміру на обох лекціях: заміна одного
# слова "правило" на "важливе" обвалила другу лекцію до 4-5/14.
RULES_PROMPT = """Нижче - пронумеровані речення зі стенограми лекції. У кожному є число (цифрами або словом).
Розклади їх на два списки:
- rules - речення, де число стосується правил цього курсу: бали й оцінювання, строки й дати, кількість робіт чи тестів, умови атестацій і заліку, перездачі, тривалість семестру, статистика оцінок у цьому курсі, обсяг завдань.
  Для кожного - id і fact: одне коротке твердження українською, що саме сказано, з числами точно як у реченні. Не округлюй, не обчислюй, не додавай того, чого немає в реченні. Контекст (попереднє речення) - лише щоб зрозуміти, до чого число.
- background - номери всіх інших речень: скільки людей на занятті, номери аудиторій, роки й події з історії, опитування, новини, приклади й обчислення з матеріалу лекції, а також коли слово-числівник не означає кількість ("один з варіантів").

Кожен id - рівно в одному зі списків.

РЕЧЕННЯ:
"""

# Прохід 2. Питання таке саме вузьке: не "важливе", а "чи має слухач щось
# зробити". Числа тут не згадуються навмисно - строк може бути й без числа
# ("до наступного заняття"), а бали вже знайшов перший прохід.
TASKS_PROMPT = """Нижче - пронумеровані речення зі стенограми лекції. У кожному є наказовий спосіб або слово про обов'язок чи строк.
Розклади їх на два списки:
- rules - речення, де названо конкретну дію, яку має зробити слухач курсу: надіслати, записатися, зареєструватися, повідомити, принести, показати, пройти тест, здати роботу, оформити, виконати до строку.
  Для кожного - id і fact: одне коротке твердження українською, що саме треба зробити, з умовою й строком, якщо вони названі, і з числами точно як у реченні. Не округлюй, не обчислюй, не додавай того, чого немає в реченні. Контекст (попереднє речення) - лише щоб зрозуміти, про що мова.
- background - номери всіх інших речень: те, що робитиме викладач, а не слухач; загальні міркування про предмет ("треба розуміти", "треба вміти", "потрібно знати"); пояснення матеріалу й того, що мусить робити програма чи протокол; побажання без дії; згадка обов'язку без того, що саме зробити.

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
    return llm.ask(prompt, seed=seed, predict=6000, fmt=SCHEMA)


def _render(items, num):
    """num: {id речення -> номер у цьому проході}. Нумерація локальна й
    неперервна - прохід із правилами має бачити рівно той текст, на якому
    зміряно 23/23, хоча набір кандидатів тепер ширший."""
    return "\n".join(f"[{num[m['id']]}] ({m['ts']}) Контекст: {m['prev'] or '-'}\n    Речення: {m['text']}"
                     for m in items)


def _one_pass(items, prompt, seed, retries, stats):
    """({id: fact}, [propushcheni id]). Fon ne zapysuyet'sya: rechennya, yake
    cej prokhid nazvav fonom, mozhe shche prydatysya drugomu prokhodu."""
    num = {m["id"]: i + 1 for i, m in enumerate(items)}
    back = {v: k for k, v in num.items()}
    got, answered, todo = {}, set(), items
    for _ in range(1 + retries):
        if not todo:
            break
        for k in range(0, len(todo), BATCH):
            part = todo[k:k + BATCH]
            r = _ask(prompt + _render(part, num), seed)
            stats["calls"] += 1
            stats["out_tokens"] += r.get("eval_count", 0)
            stats["seconds"] += r.get("total_duration", 0) / 1e9
            try:
                ans = json.loads(r["response"])
            except json.JSONDecodeError:
                # Обрізана відповідь: уся пачка піде на повтор, а не в тишу.
                stats["truncated"] += 1
                continue
            local = {num[m["id"]] for m in part}
            for it in ans.get("rules", []):
                if it.get("id") in local and back[it["id"]] not in answered:
                    answered.add(back[it["id"]])
                    got[back[it["id"]]] = it.get("fact", "").strip()
            for j in ans.get("background", []):
                if j in local and back[j] not in answered:
                    answered.add(back[j])
        todo = [m for m in todo if m["id"] not in answered]
    return got, [m["id"] for m in todo]


def classify(ms, seed=42, retries=2):
    """{id: {kind, fact}} z dvokh prokhodiv. Rechennya, de ye i chyslo, i
    oznaka diyi, jde v oba; "pravylo" perevazhaye - joho formulyuvannya
    zmiryane, a "zavdannya" - shche ni."""
    stats = {"calls": 0, "out_tokens": 0, "seconds": 0.0, "truncated": 0}
    with_num = [m for m in ms if m.get("num")]
    with_task = [m for m in ms if m.get("task")]
    rules, miss_r = _one_pass(with_num, RULES_PROMPT, seed, retries, stats)
    tasks, miss_t = _one_pass(with_task, TASKS_PROMPT, seed, retries, stats)
    got = {}
    for m in ms:
        i = m["id"]
        if rules.get(i):
            got[i] = {"kind": "правило", "fact": rules[i]}
        elif tasks.get(i):
            got[i] = {"kind": "завдання", "fact": tasks[i]}
        else:
            got[i] = {"kind": "фон", "fact": ""}
    kinds = collections.Counter(g["kind"] for g in got.values())
    stats.update({"n_num": len(with_num), "n_task": len(with_task),
                  "n_rules": kinds["правило"], "n_tasks": kinds["завдання"],
                  "missing_rules": miss_r, "missing_tasks": miss_t,
                  # Пропущене хоч в одному проході, куди речення відправляли:
                  # "фон тут, тиша там" - теж утрата, а не відповідь.
                  "missing_after": sorted(set(miss_r) | set(miss_t))})
    return got, stats


def lost_digits(sentence, fact):
    """Chysla rechennya, yakykh brakuye u formulyuvanni - z urakhuvannyam
    kil'kosti vkhodzhen': "7 laboratornykh, 6 i 7 neobov'yazkovi" -> "laby 6 i 7
    neobov'yazkovi" vtrachaye same druhu simku, i mnozhyna ts'oho ne pobachyt'."""
    have = collections.Counter(re.findall(r"\d+", fact))
    return list((collections.Counter(re.findall(r"\d+", sentence)) - have).elements())


def section(ms, got):
    """Odyn spysok "Vazhlyve" u poryadku prozvuchannya, z tajmkodamy - kozhne
    chyslo mozhna pereviryty v zapysi. Pravyla j zavdannya ne rozdilyayut'sya
    mitkamy: ce bulo rishennya 1.3 - zaranee prydumani kategoriyi prybrano.
    Yakshcho formulyuvannya zahubylo chyslo z rechennya, do ryadka dodayet'sya
    dosliva cytata: zahubyty movchky ne mozhna."""
    rows = []
    for m in ms:
        g = got.get(m["id"])
        if not g or g["kind"] == "фон" or not g["fact"]:
            continue
        row = f"- [{m['ts']}] {g['fact']}"
        if lost_digits(m["text"], g["fact"]):
            row += f" — дослівно: «{m['text']}»"
        rows.append(row)
    return "\n".join(rows) if rows else "немає"
