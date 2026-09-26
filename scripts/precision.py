# -*- coding: utf-8 -*-
"""Tochnist' rozdilu "Vazhlyve": skil'ky ryadkiv u n'omu spravdi potribni.

Chomu okremyj etalon. Povnota mirayet'sya shablonamy faktiv (FACTS u
numbers-probe.py) - ce recall. Vona nichoho ne kazhe pro te, shcho v rozdili
shche 60 ryadkiv smittya: na druhij lekciyi model' nazvala "pravylom" 50-81
rechennya z 87, a vsi 13 faktiv etalona pry tomu na misci. Promt pravyvsya
nayoslip same tomu, shcho druhoho chysla ne bulo.

Etalon trymayet'sya za RECHENNYA, ne za formulyuvannya modeli: klyuch - ce
tajmkod plyus hesh rechennya stenohramy. Tomu rozmitka perezhyvaye pravku
promptu, i v git ide bez imen - lyshe klyuch i mitka.

    python scripts/precision.py --sheet l1      # zrobyty arkush dlya rozmitky
    python scripts/precision.py                 # porakhuvaty tochnist'
"""
import argparse, collections, csv, glob, hashlib, json, pathlib, re, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import protocol_numbers

ROOT = pathlib.Path(__file__).resolve().parent.parent
LABELS = ROOT / "data" / "precision-labels.tsv"
SHEETS = ROOT / "out" / "numbers" / "precision"      # з іменами - у git не йде

PAIRS = {
    "l1":       "out/numbers/extract__t0.2__s*.json",
    "l2":       "out/numbers/l2__extract__t0.2__s*.json",
    "math":     "out/numbers/math_2pass_s1.json",
    # Той самий шар, але лише в організаційних вікнах пари (--org).
    "l1-org":   "out/numbers/org__extract__t0.2__s*.json",
    "l2-org":   "out/numbers/l2__org__extract__t0.2__s*.json",
    "math-org": "out/numbers/math_2pass_org_s1.json",
    # Третя пара з правилами, шару не знайома (знайдена перебором).
    "l3":       "out/numbers/l3__extract__t0.2__s*.json",
    "l3-org":   "out/numbers/l3__org__extract__t0.2__s*.json",
    # Те саме плюс захоплення 60 с за межею вікна (--margin 60): блок не
    # вирівняний по сітці 5 хв, і вікно з його хвостом модель кличе матеріалом.
    "l1-org60":   "out/numbers/org60__extract__t0.2__s*.json",
    "l2-org60":   "out/numbers/l2__org60__extract__t0.2__s*.json",
    "l3-org60":   "out/numbers/l3__org60__extract__t0.2__s*.json",
    # Математика через скрипт, а не руками: старі math_2pass_* були зроблені
    # разово, і умову того прогону (які вікна, який захват) відтворити нічим.
    "math-org0":  "out/numbers/math__org__extract__t0.2__s*.json",
    "math-org60": "out/numbers/math__org60__extract__t0.2__s*.json",
    # Розмір пачки (--batch): гіпотеза "модель судить відносно пачки".
    "l1-org60b20": "out/numbers/org60__b20__extract__t0.2__s*.json",
    "l2-org60b20": "out/numbers/l2__org60__b20__extract__t0.2__s*.json",
    "l3-org60b20": "out/numbers/l3__org60__b20__extract__t0.2__s*.json",
    "l3-org60b10": "out/numbers/l3__org60__b10__extract__t0.2__s*.json",
    "l3-org60b1":  "out/numbers/l3__org60__b1__extract__t0.2__s*.json",
    # Третій прохід (--orgw + COND_PROMPT, пункт (б)).
    "l1-org60w":        "out/numbers/org60__w__extract__t0.2__s*.json",
    "l2-org60w":        "out/numbers/l2__org60__w__extract__t0.2__s*.json",
    "l3-org60w":        "out/numbers/l3__org60__w__extract__t0.2__s*.json",
    "ksi260904-org60w": "out/numbers/ksi260904__org60__w__extract__t0.2__s*.json",
    "prac2-org60w":     "out/numbers/prac2__org60__w__extract__t0.2__s*.json",
    "prac4-org60w":     "out/numbers/prac4__org60__w__extract__t0.2__s*.json",
    # Пари з нових записів: еталону повноти немає, міряється лише точність.
    "ksi260904-org60": "out/numbers/ksi260904__org60__extract__t0.2__s*.json",
    "prac2-org60":     "out/numbers/prac2__org60__extract__t0.2__s*.json",
    "prac4-org60":     "out/numbers/prac4__org60__extract__t0.2__s*.json",
}

# Мітки спільні: вужчий прогін дає підмножину тих самих речень, і розмічати
# їх удруге означало б дозволити собі поставити іншу межу під результат.
LABEL_OF = {k: re.sub(r"-org\d*(b\d+)?w?$", "", k) for k in PAIRS}

# Стенограми для розмітки по КАНДИДАТАХ (--cand). Чому не по рядках розділу:
# рядки - це те, що модель видала, і правильно відкинутого в них немає взагалі.
# Тому таку розмітку не можна ні перевикористати після правки промпта (нові
# рядки щоразу нерозмічені), ні навчати на ній - вона закріплює саме поточні
# ложні срабатывания. Мітка на кожному кандидаті від версії не залежить.
TRANSCRIPTS = {
    "l1":        "data/transcripts/lecture_long_65min.txt",
    "l2":        "out/asr/whisper-large-v3+fb+vad-p260210.txt",
    "math":      "out/asr/whisper-large-v3+fb+vad-p0206.txt",
    "l3":        "out/asr/whisper-large-v3+fb+vad-p250205org.txt",
    "ksi260904": "out/asr/whisper-large-v3+fb+vad-ksi260904.txt",
    "prac2":     "out/asr/whisper-large-v3+fb+vad-prac2.txt",
    "prac4":     "out/asr/whisper-large-v3+fb+vad-prac4.txt",
}
SAMPLE_SEED = 20260925        # той самий, що в жеребі поділу набору

# Пари, розмічені по кандидатах (--cand), а не по рядках розділу. Лише для них
# у знаменнику повноти стоять УСІ вимоги пари, тому лише для них це число
# означає повноту. Список ведеться руками: він про спосіб розмітки, а не про
# наявність файлу.
CAND_LABELLED = {"ksi260904", "prac2", "prac4", "l3"}


def key(ts, text):
    """Tajmkod i hesh rechennya. Hesh - vid normalizovanoho tekstu, shchob
    dribna zmina rozbyttya na rechennya ne znecinyla rozmitku movchky: yakshcho
    rechennya vse zh zminylosya, klyuch ne znajdet'sya i scoring pro ce skazhe."""
    t = re.sub(r"\s+", " ", text.replace("’", "'").replace("ʼ", "'")).strip().lower()
    return ts.replace(":", "") + "-" + hashlib.sha1(t.encode("utf-8")).hexdigest()[:6]


def rows(pair):
    """{key: {ts, text, fact, n, seeds, kinds}} - kozhne rechennya, yake khot'
    v odnomu prokhoni potrapylo v rozdil."""
    files = sorted(glob.glob(str(ROOT / PAIRS[pair])))
    out = {}
    for p in files:
        for x in json.load(open(p, encoding="utf-8"))["items"]:
            if x.get("kind") in ("правило", "завдання", "умова") and x.get("fact"):
                r = out.setdefault(key(x["ts"], x["text"]),
                                   {"ts": x["ts"], "text": x["text"], "fact": x["fact"],
                                    "n": 0, "kinds": collections.Counter()})
                r["n"] += 1
                r["kinds"][x["kind"]] += 1
    return out, len(files)


def load_labels():
    if not LABELS.exists():
        return {}
    got = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        pair, k, mark = line.split("\t")[:3]
        got[(pair, k)] = mark.strip()
    return got


def load_authors():
    """{(para, klyuch): khto postavyv}. Chetverta kolonka; staryj fajl bez neyi
    chytayet'sya yak "m" - do ciyeyi pravky rozmichav lyshe vin."""
    got = {}
    if not LABELS.exists():
        return got
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) >= 3:
            got[(f[0], f[1])] = (f[3].strip() if len(f) > 3 and f[3].strip() else "m")
    return got


HEAD = """# Розмітка точності розділу «Важливе» — {pair}, {n} рядків, {seeds} прогонів.
#
# Поміть перший символ рядка:
#   +  рядок у розділі потрібен
#   -  сміття: не правило курсу і не дія слухача
#   =  правда, але вже сказана іншим рядком (дубль)
# Порожньо = ще не розмічено, такі рядки не потрапляють у число.
# Дублі окремо від сміття навмисно: це різні хвороби, і лікуються різно -
# сміття промптом, дублі склейкою однакових фактів у section().
#
# Ключ — таймкод і хеш речення. Розмітка тримається за речення стенограми,
# а не за формулювання моделі, тому переживає правку промптів.
# Формат: мітка | ключ | у скількох прогонах | прохід | формулювання моделі || речення
"""


def sheet(pair):
    rs, seeds = rows(pair)
    old = {k: m for (p, k), m in load_labels().items() if p == LABEL_OF[pair]}
    SHEETS.mkdir(parents=True, exist_ok=True)
    path = SHEETS / f"{pair}.txt"
    lines = [HEAD.format(pair=pair, n=len(rs), seeds=seeds)]
    for k, r in sorted(rs.items(), key=lambda kv: (kv[1]["ts"], kv[0])):
        kind = "+".join(sorted(r["kinds"]))
        lines.append(f"{old.get(k, '')}\t{k}\t{r['n']}/{seeds}\t{kind}\t"
                     f"{r['fact']}\t||\t{r['text']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    marked = sum(1 for k in rs if old.get(k))
    print(f"{path}: {len(rs)} rows, {marked} already marked")


CAND_HEAD = """# Розмітка КАНДИДАТІВ — {pair}, {n} речень{note}, розмічено {marked}.
#
# Мітка — про РЕЧЕННЯ СТЕНОГРАМИ, не про рядок розділу. Поміть перший символ:
#   +  вимога курсу або дія слухача: цьому місце в розділі «Важливе»
#   -  фон: матеріал, приклади, обчислення, міркування про фах, справи викладача
#   =  правда, але цей самий факт уже сказаний іншим кандидатом раніше
#   г  правда, але місце цьому в главах, а не в «Важливе»: структура курсу,
#      про що була пара. У точності рахується як не потрібне тут (2026-09-26).
# Порожньо = ще не розмічено, такі речення в число не йдуть.
#
# Ознака, за якою речення взяте в кандидати: ч - число, д - наказ або слово про
# обов'язок чи строк, с - словник організаційного (третій критерій, пункт (б)).
# «модель:» - як це речення сформулювала модель, якщо воно колись потрапляло в
# розділ; це довідка, а не підказка: мітка ставиться по реченню, і саме тому
# вона переживає будь-яку правку промпта.
#
# Формат: мітка | ключ | ознака | модель | || | речення | ← контекст
"""


def _model_facts(pair):
    """{klyuch: formulyuvannya} z usikh armiv ciyeyi pary - lyshe yak dovidka."""
    out = {}
    for name, pat in PAIRS.items():
        if LABEL_OF[name] != pair:
            continue
        for p in sorted(glob.glob(str(ROOT / pat))):
            for x in json.load(open(p, encoding="utf-8"))["items"]:
                if x.get("fact"):
                    out.setdefault(key(x["ts"], x["text"]), x["fact"])
    return out


def sheet_cand(pair, sample=0):
    """Arkush po vsikh kandydatakh pary: kozhne rechennya, yake vidbir kodu
    viddaye modeli (chyslo, nakaz abo slovnyk), z mitkoyu, yaka vzhe stoyit'."""
    import random
    text = (ROOT / TRANSCRIPTS[pair]).read_text(encoding="utf-8")
    ms = protocol_numbers.mentions(text, org=True)
    note = ""
    if sample and len(ms) > sample:
        pick = random.Random(SAMPLE_SEED).sample(range(len(ms)), sample)
        ms = [ms[i] for i in sorted(pick)]
        note = f" (вибірка {sample} з жеребом {SAMPLE_SEED})"
    old = {k: m for (p, k), m in load_labels().items() if p == pair}
    facts = _model_facts(pair)
    SHEETS.mkdir(parents=True, exist_ok=True)
    path = SHEETS / f"{pair}.cand.txt"
    lines, marked = [], 0
    for m in ms:
        k = key(m["ts"], m["text"])
        marked += bool(old.get(k))
        sign = ("ч" if m["num"] else "") + ("д" if m["task"] else "") + ("с" if m.get("orgw") else "")
        lines.append(f"{old.get(k, '')}\t{k}\t{sign}\t{facts.get(k, '-')}\t||\t{m['text']}"
                     f"\t← {m['prev'] or '-'}")
    path.write_text(CAND_HEAD.format(pair=pair, n=len(ms), note=note, marked=marked)
                    + "\n".join(lines) + "\n", encoding="utf-8")
    by = collections.Counter(("ч" if m["num"] else "") + ("д" if m["task"] else "")
                             + ("с" if m.get("orgw") else "") for m in ms)
    print(f"{path}: {len(ms)} речень, розмічено {marked}, лишилось {len(ms) - marked}")
    print("   за ознакою: " + ", ".join(f"{s or '?'} {c}" for s, c in sorted(by.items())))


def collect(pair, cand=False):
    """Arkush -> data/precision-labels.tsv (lyshe klyuch i mitka, bez imen)."""
    path = SHEETS / (f"{pair}.cand.txt" if cand else f"{pair}.txt")
    got = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("\t")
        if f[0].strip() in ("+", "-", "="):
            got[f[1]] = f[0].strip()
    return got


def save_labels(new, who="m"):
    old, authors = load_labels(), load_authors()
    old.update(new)
    authors.update({k: who for k in new})
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    body = ["# Еталон точності розділу «Важливе»: які речення в розділі потрібні.",
            "# Пара, ключ (таймкод + хеш речення), мітка, автор. Тексту тут немає — імена.",
            "# Автор: m - ручна розмітка, o - автоматична (LLM). Числа, які стоять на",
            "# автоматичній розмітці, це модель проти моделі, і в журналі це має бути",
            "# сказано прямо.",
            "# Аркуші для розмітки: out/numbers/precision/<пара>.cand.txt (у git не йдуть)."]
    for (pair, k), mark in sorted(old.items()):
        body.append(f"{pair}\t{k}\t{mark}\t{authors.get((pair, k), 'm')}")
    LABELS.write_bytes(("\n".join(body) + "\n").encode("utf-8"))
    by = collections.Counter(authors.get(k, "m") for k in old)
    print(f"{LABELS}: {len(old)} labels ({', '.join(f'{a}: {c}' for a, c in sorted(by.items()))})")


def scoreboard(csv_path):
    labels = load_labels()
    out = []
    for pair in PAIRS:
        files = sorted(glob.glob(str(ROOT / PAIRS[pair])))
        for p in files:
            items = json.load(open(p, encoding="utf-8"))["items"]
            # Рахуються РЯДКИ РОЗДІЛУ, а не кандидати: після склейки переказів
            # один рядок покриває кілька речень, і поки скорер рахував речення,
            # склейка була йому невидна - число не змінилося б узагалі.
            got = {x["id"]: {"kind": x["kind"], "fact": x["fact"]}
                   for x in items if "kind" in x}
            ms = [{k: x[k] for k in ("id", "ts", "text", "prev")} for x in items]
            by_id = {x["id"]: x for x in items}
            good = bad = dup = unknown = mixed = 0
            for r in protocol_numbers.section_rows(ms, got):
                marks = {labels.get((LABEL_OF[pair], key(by_id[i]["ts"], by_id[i]["text"])))
                         for i in r["ids"]}
                # Рядок потрібен, якщо несе хоч один потрібний факт; дубль -
                # якщо всі його речення лише повторюють сказане.
                if None in marks and not (marks - {None}):
                    unknown += 1
                elif "+" in marks:
                    good += 1
                    mixed += "-" in marks      # склейка "потрібне + сміття": відмивання
                elif "=" in marks:
                    dup += 1
                else:
                    bad += 1
            total = good + bad + dup + unknown
            # Точність рахується лише по розміченому; нерозмічене видно окремо,
            # щоб нове формулювання не покращило число тишею. Дубль у числі
            # точності - не потрібен: читач бачить той самий факт двічі.
            known = good + bad + dup
            prec = round(good / known, 3) if known else ""
            # Повнота з тієї самої розмітки: скільки речень, помічених "+",
            # дійшло до розділу. Має сенс ЛИШЕ для пар, розмічених по
            # кандидатах (--cand): там знаменник - усі вимоги пари. Для пар,
            # розмічених по рядках розділу, у знаменнику тільки те, що модель
            # колись видала, і число вийшло б завищеним - тому "".
            plus = {k for (pp, k), m in labels.items() if pp == LABEL_OF[pair] and m == "+"}
            in_rows = {key(by_id[i]["ts"], by_id[i]["text"])
                       for r in protocol_numbers.section_rows(ms, got) for i in r["ids"]}
            cand = LABEL_OF[pair] in CAND_LABELLED
            out.append({"pair": pair, "seed": re.search(r"s(\d+)\.json$", p).group(1),
                        "rows": total, "needed": good, "junk": bad, "dup": dup,
                        "unlabelled": unknown, "mixed": mixed, "precision": prec,
                        "plus_total": len(plus) if cand else "",
                        "plus_found": len(plus & in_rows) if cand else ""})
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    for r in out:
        print(f"{r['pair']:16} s{r['seed']}  rows {r['rows']:3}  need {r['needed']:3}  "
              f"junk {r['junk']:3}  dup {r['dup']:3}  unlabelled {r['unlabelled']:3}  "
              f"precision {r['precision']}"
              + (f"  повнота {r['plus_found']}/{r['plus_total']}" if r["plus_total"] != "" else "")
              + ("  ! mixed %d" % r['mixed'] if r['mixed'] else ""))
    if any(r["unlabelled"] for r in out):
        print("! є нерозмічені рядки - число неповне, зроби --sheet і розміть")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", choices=list(PAIRS) + list(TRANSCRIPTS),
                    help="зробити аркуш для розмітки")
    ap.add_argument("--collect", choices=list(PAIRS) + list(TRANSCRIPTS),
                    help="забрати мітки з аркуша в еталон")
    ap.add_argument("--cand", action="store_true",
                    help="аркуш по всіх кандидатах пари, а не по рядках розділу")
    ap.add_argument("--sample", type=int, default=0,
                    help="узяти лише N кандидатів жеребом (для математики: 503 цілком нащо)")
    ap.add_argument("--who", default="m", choices=["m", "o"],
                    help="хто поставив мітки: m - він, o - модель")
    ap.add_argument("--csv", default=str(ROOT / "results" / f"precision_{time.strftime('%Y-%m-%d')}.csv"))
    a = ap.parse_args()
    if a.sheet:
        sheet_cand(a.sheet, a.sample) if a.cand else sheet(a.sheet)
    elif a.collect:
        pair = LABEL_OF.get(a.collect, a.collect)
        save_labels({(pair, k): m for k, m in collect(a.collect, a.cand).items()}, a.who)
    else:
        scoreboard(a.csv)


if __name__ == "__main__":
    main()
