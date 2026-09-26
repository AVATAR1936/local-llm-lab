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
import collections, json, os, pathlib, re, sys

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

# Третій критерій відбору (пункт (б) плану): слова організаційної області.
# Вимога буває без числа й без наказу - "у груп ФЄ це екзамен, а у ФБ залік",
# "ставитиму автоматом": ні NUM, ні TASK її не бачать, і до моделі вона не
# доїжджає взагалі. Це той самий словник, за яким перебір відрізняє
# організаційну пару від предметної.
# Типово вимкнений (mentions(org=False)): набір кандидатів - умова, на якій
# зміряно і повноту, і точність, і зсувати її без окремого заміру не можна.
ORGW = re.compile(r"(?<![\w'])(?:силабус\w*|сілабус\w*|форм\w*\s+контролю|практикум\w*|модульн\w*|"
                  r"атестац\w*|залік\w*|екзамен\w*|автоматом|перездач\w*|звіт\w*|конспект\w*|"
                  r"лаборатор\w*|реферат\w*|курсов\w*|класрум\w*|classroom|методичк\w*|"
                  r"оформ\w*|формат\w*)(?![\w'])", re.I)


def _norm_apos(t):
    return t.replace("’", "'").replace("ʼ", "'")


def _secs(ts):
    h, m, s = (int(x) for x in ts.split(":"))
    return h * 3600 + m * 60 + s


def within(ms, ranges):
    """Kandydaty, tajmkod yakykh potrapyv u odyn z vidrizkiv. Id ne
    perenumerovuyut'sya: etalon tochnosti trymayet'sya za tajmkod i tekst."""
    return [m for m in ms if any(a <= _secs(m["ts"]) < b for a, b in ranges)]


def mentions(transcript, org=False):
    """[{id, ts, text, prev}] - rechennya z chyslamy. Shapka fajlu (rядky z #)
    - ne stenohrama: tam model' rozpiznavannya i chas obrobky.

    org=True dodaye tretij kryterij (ORGW): vymohy bez chysla j bez nakazu.
    Typovo vyklyucheno - nabir kandydativ ce umova zamiru."""
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
        num, task, orgw = bool(NUM.search(s)), bool(TASK.search(s)), bool(ORGW.search(s))
        if num or task or (org and orgw):
            out.append({"id": len(out) + 1, "ts": ts, "text": s,
                        "prev": sents[i - 1][1] if i else "",
                        "num": num, "task": task, "orgw": orgw})
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
#
# Правка 2026-09-25 після заміру на третій парі. Зі списку "фон" знято дві
# лазівки, і кожна коштувала фактів:
#  * "згадка обов'язку без того, що саме зробити" - моє ж додавання, яке
#    обвалило K04 (6/6 -> 1/6) і K05 (2/6 -> 0/6) на першій лекції, а на
#    третій забрало "додаткове завдання в четвертому практикумі" й "можна
#    закрити на мінімальний бал";
#  * "те, що мусить робити програма чи протокол" - звалювало в одне
#    пояснення матеріалу і ВИМОГИ ДО ЗВІТУ, через що пішли у фон "код має
#    бути читабільний" і "протокол здавати в Google Classroom".
# Замість них у "фон" названо те, що справді має там бути: гасла самої
# дисципліни ("захищайте інформацію" як закон предмета) - на них шар
# спіймався на парі про OPSEC, усі 7 рядків розділу були такими.
TASKS_PROMPT = """Нижче - пронумеровані речення зі стенограми лекції. У кожному є наказовий спосіб або слово про обов'язок чи строк.
Розклади їх на два списки:
- rules - речення, з якого видно, що слухач курсу має зробити або якою має бути його робота:
  - дія: надіслати, записатися, зареєструватися, повідомити, принести, показати, пройти тест, здати роботу, виконати до строку;
  - вимога до роботи чи звіту: що в ньому має бути, як оформлений, куди і в якому вигляді його здавати, що дозволено, а чого не вимагають;
  - додаткове чи необов'язкове завдання і за що воно дається; умова, за якої роботу можна закрити на менший бал.
  Це може бути сказано наказом, констатацією або навіть питанням студента з відповіддю - важливо лише, чи видно з речення саму вимогу.
  Для кожного - id і fact: одне коротке твердження українською, що саме треба зробити або якою має бути робота, з умовою й строком, якщо вони названі, і з числами точно як у реченні. Не округлюй, не обчислюй, не додавай того, чого немає в реченні. Контекст (попереднє речення) - лише щоб зрозуміти, про що мова.
- background - номери всіх інших речень: пояснення самого предмета - означення, приклади, обчислення, розбір задач, і те, що має робити програма за умовою задачі; гасла й правила самої дисципліни, які вивчаються як матеріал ("захищайте інформацію" як закон предмета); загальні міркування про фах ("треба розуміти", "треба вміти", "потрібно знати"); те, що робить викладач і що не стосується роботи слухача; побажання й підбадьорювання без вимоги.

Кожен id - рівно в одному зі списків.

РЕЧЕННЯ:
"""

# Прохід 3 (пункт (б) плану, маршрут для ORGW). Вхід - лише ті кандидати, яких
# перші два проходи НЕ бачать: слово організаційної області без числа й без
# наказу. Тому промпти перших двох лишаються побайтово тими самими, і числа,
# зміряні на них, не зсуваються.
#
# Нащо окремий прохід. Ланцюг утрат (3g плану): на організаційній лекції сім
# вимог із сімнадцяти не доходять до моделі взагалі, і всі сім саме такі -
# "ФЄ це екзамен, а у ФБ залік", "ставитиму автоматом", "практикуми можна
# виконати", "на практикум працюєте самотужки". Питання тут третє й вузьке:
# не "важливе", не "чи має слухач щось зробити", а "чи названа УМОВА навчання".
COND_PROMPT = """Нижче - пронумеровані речення зі стенограми заняття. У кожному названо щось із навчального устрою: форма контролю, залік чи екзамен, практикум, лабораторна, звіт, силабус, автомат, перездача, методичка, формат здачі.
Розклади їх на два списки:
- rules - речення, з якого видно УМОВУ навчання на цьому курсі: яка форма контролю і в кого саме, чим її можна закрити, скільки й яких робіт, поодинці чи командою вони робляться, як і куди здаються, де лежать матеріали й правила, що дозволено, а чого не вимагають.
  Для кожного - id і fact: одне коротке твердження українською, що саме є умовою, з числами точно як у реченні. Не округлюй, не обчислюй, не додавай того, чого немає в реченні. Контекст (попереднє речення) - лише щоб зрозуміти, про що мова.
- background - номери всіх інших речень: пояснення самого предмета, де ці слова означають матеріал ("оцінювання захищеності", "звіт" як документ системи, "практикум" як приклад); згадка, що щось "є в силабусі" чи "під номером у списку джерел", без самої умови; розповіді про минулі роки, інші курси й те, як було раніше; обривки речень, з яких умови не видно; дії викладача, що не стосуються слухача.

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


# Katalog dlya vyhruzky promptiv. Yakshcho zadanyj - model' ne vyklykayet'sya
# vzahali: verkhnya mezha mirayet'sya na TOMU SAMOMU teksti, shcho jde v gemma,
# inakshe chysla nesporivnyanni.
DUMP = None


def _one_pass(items, prompt, seed, retries, stats, batch=None, tag="pass"):
    """({id: fact}, [propushcheni id]). Fon ne zapysuyet'sya: rechennya, yake
    cej prokhid nazvav fonom, mozhe shche prydatysya drugomu prokhodu."""
    num = {m["id"]: i + 1 for i, m in enumerate(items)}
    if DUMP is not None:
        step = batch or BATCH
        for k in range(0, len(items), step):
            part = items[k:k + step]
            out = pathlib.Path(DUMP) / f"{tag}-{k // step + 1}.txt"
            out.write_text(prompt + _render(part, num), encoding="utf-8")
        return {}, []
    back = {v: k for k, v in num.items()}
    got, answered, todo = {}, set(), items
    for _ in range(1 + retries):
        if not todo:
            break
        for k in range(0, len(todo), batch or BATCH):
            part = todo[k:k + (batch or BATCH)]
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


def classify(ms, seed=42, retries=2, batch=None):
    """{id: {kind, fact}} z tr'okh prokhodiv. Rechennya, de ye i chyslo, i
    oznaka diyi, jde v oba pervykh; "pravylo" perevazhaye - joho formulyuvannya
    zmiryane, a "zavdannya" - shche ni.

    Tretij prokhid (COND_PROMPT) otrymuye LYSHE kandydativ, yakykh pervi dva ne
    bachat': slovo organizacijnoyi oblasti bez chysla j bez nakazu. Yakshcho
    takykh nemaye - a pry mentions(org=False) ikh i ne buvaye - prokhid ne
    vyklykayet'sya vzahali, i umova starykh zamiriv ne zsuvayet'sya."""
    stats = {"calls": 0, "out_tokens": 0, "seconds": 0.0, "truncated": 0}
    with_num = [m for m in ms if m.get("num")]
    with_task = [m for m in ms if m.get("task")]
    with_cond = [m for m in ms if m.get("orgw") and not m.get("num") and not m.get("task")]
    rules, miss_r = _one_pass(with_num, RULES_PROMPT, seed, retries, stats, batch, "rules")
    tasks, miss_t = _one_pass(with_task, TASKS_PROMPT, seed, retries, stats, batch, "tasks")
    conds, miss_c = ({}, []) if not with_cond else \
        _one_pass(with_cond, COND_PROMPT, seed, retries, stats, batch, "cond")
    got = {}
    for m in ms:
        i = m["id"]
        if rules.get(i):
            got[i] = {"kind": "правило", "fact": rules[i]}
        elif tasks.get(i):
            got[i] = {"kind": "завдання", "fact": tasks[i]}
        elif conds.get(i):
            got[i] = {"kind": "умова", "fact": conds[i]}
        else:
            got[i] = {"kind": "фон", "fact": ""}
    kinds = collections.Counter(g["kind"] for g in got.values())
    stats.update({"n_num": len(with_num), "n_task": len(with_task), "n_cond": len(with_cond),
                  "n_rules": kinds["правило"], "n_tasks": kinds["завдання"],
                  "n_conds": kinds["умова"],
                  "missing_rules": miss_r, "missing_tasks": miss_t, "missing_conds": miss_c,
                  # Пропущене хоч в одному проході, куди речення відправляли:
                  # "фон тут, тиша там" - теж утрата, а не відповідь.
                  "missing_after": sorted(set(miss_r) | set(miss_t) | set(miss_c))})
    return got, stats


def lost_digits(sentence, fact):
    """Chysla rechennya, yakykh brakuye u formulyuvanni - z urakhuvannyam
    kil'kosti vkhodzhen': "7 laboratornykh, 6 i 7 neobov'yazkovi" -> "laby 6 i 7
    neobov'yazkovi" vtrachaye same druhu simku, i mnozhyna ts'oho ne pobachyt'."""
    have = collections.Counter(re.findall(r"\d+", fact))
    return list((collections.Counter(re.findall(r"\d+", sentence)) - have).elements())


# --- склейка переказів -----------------------------------------------------
# Той самий факт лектор повторює: "70 балів за лабораторні" о 00:44:12 і
# "на лабораторні виділяється 70 балів" о 00:44:34. Розмічено 15 таких рядків
# на трьох парах.
#
# Зміряно (2026-09-25) і саме тому правило тут одне й вузьке:
#  * схожість формулювань дублі НЕ відділяє. Два різних потрібних рядки
#    лекції 1 дають перекриття 1.00, а дублі опускаються до 0.33: межі немає.
#    Причина - формулювання худі, і "той самий факт" часто вирішує те, що з
#    формулювання зникло ("по знанню РТСУ", "його треба пройти").
#  * правило "черга реплік" (сусідні кандидати впритул за часом) на
#    математиці склеює правильно, а на лекції 1 склеїло 22 різних факти:
#    там розділ щільний, і сусідні кандидати - різні правила. Відкинуто.
# Лишилося те, що не шкодить: ті самі числа плюс схожі слова. Бере 1-2 дублі
# з 15, шкоди 0. Решта - рішення про окремий прохід моделі, не код.
_STOP = set("це цей ця той та як що ще вже там тут вам ви ми не і й а але бо за на у в з із "
            "до по про від для при або чи так ну от тобто буде бути є має маєте можна "
            "потрібно треба все свої".split())


def _words(fact):
    """Chotyry pervi litery znachushchykh sliv: hrubyj zaminnyk lematyzaciyi,
    "laboratornykh" i "laboratorni" stayut' odnym."""
    return {w[:4] for w in re.findall(r"[\w']+", fact.lower())
            if len(w) >= 4 and w not in _STOP and not w.isdigit()}


def _same_fact(a, b, jac_min=0.6):
    """Ti sami chysla (abo v oboh zhodnoho) i schozhi slova. Ryadok, u yakomu
    menshe tr'okh znachushchykh sliv, ne porivnyuyet'sya: "Bude dva testy" daye
    odne slovo i skhozhyj na vse pro testy."""
    if collections.Counter(re.findall(r"\d+", a)) != collections.Counter(re.findall(r"\d+", b)):
        return False
    wa, wb = _words(a), _words(b)
    if len(wa) < 3 or len(wb) < 3:
        return False
    return len(wa & wb) / len(wa | wb) >= jac_min


def section_rows(ms, got, merge=True):
    """[{ids, ts, ts_end, fact, quote}] - ryadky rozdilu do vidmalyovky.
    Okremo vid section(), shchob zamir tochnosti rakhuvav same ryadky, yaki
    pobachyt' chytach: poky skorer rakhuvav kandydativ, sklejka bula jomu
    nevydna, i chyslo ne zminylosya b vzahali."""
    rows = []
    for m in ms:
        g = got.get(m["id"])
        if not g or g["kind"] == "фон" or not g["fact"]:
            continue
        rows.append({"ids": [m["id"]], "ts": m["ts"], "ts_end": m["ts"], "fact": g["fact"],
                     "quote": m["text"] if lost_digits(m["text"], g["fact"]) else ""})
    if not merge:
        return rows
    out = []
    for r in rows:
        for o in out:
            if _same_fact(o["fact"], r["fact"]):
                o["ids"] += r["ids"]
                o["ts_end"] = r["ts"]
                # Лишається повніше формулювання: більше чисел, потім довше.
                if (len(re.findall(r"\d+", r["fact"])), len(r["fact"])) > \
                   (len(re.findall(r"\d+", o["fact"])), len(o["fact"])):
                    o["fact"], o["quote"] = r["fact"], r["quote"]
                break
        else:
            out.append(r)
    return out


def section(ms, got, merge=True):
    """Odyn spysok "Vazhlyve" u poryadku prozvuchannya, z tajmkodamy - kozhne
    chyslo mozhna pereviryty v zapysi. Pravyla j zavdannya ne rozdilyayut'sya
    mitkamy: ce bulo rishennya 1.3 - zaranee prydumani kategoriyi prybrano.
    Yakshcho formulyuvannya zahubylo chyslo z rechennya, do ryadka dodayet'sya
    dosliva cytata: zahubyty movchky ne mozhna."""
    lines = []
    for r in section_rows(ms, got, merge):
        ts = r["ts"] if r["ts_end"] == r["ts"] else f"{r['ts']}–{r['ts_end']}"
        line = f"- [{ts}] {r['fact']}"
        if r["quote"]:
            line += f" — дослівно: «{r['quote']}»"
        lines.append(line)
    return "\n".join(lines) if lines else "немає"
