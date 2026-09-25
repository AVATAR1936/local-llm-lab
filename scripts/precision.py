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
import argparse, collections, csv, glob, hashlib, json, pathlib, re, time

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
}

# Мітки спільні: вужчий прогін дає підмножину тих самих речень, і розмічати
# їх удруге означало б дозволити собі поставити іншу межу під результат.
LABEL_OF = {k: k.replace("-org", "") for k in PAIRS}


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
            if x.get("kind") in ("правило", "завдання") and x.get("fact"):
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


def collect(pair):
    """Arkush -> data/precision-labels.tsv (lyshe klyuch i mitka, bez imen)."""
    path = SHEETS / f"{pair}.txt"
    got = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("\t")
        if f[0].strip() in ("+", "-", "="):
            got[f[1]] = f[0].strip()
    return got


def save_labels(new):
    old = load_labels()
    old.update(new)
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    body = ["# Еталон точності розділу «Важливе»: які речення в розділі потрібні.",
            "# Пара, ключ (таймкод + хеш речення), мітка. Тексту тут немає — імена.",
            "# Аркуші для розмітки: out/numbers/precision/<пара>.txt (у git не йдуть)."]
    for (pair, k), mark in sorted(old.items()):
        body.append(f"{pair}\t{k}\t{mark}")
    LABELS.write_bytes(("\n".join(body) + "\n").encode("utf-8"))
    print(f"{LABELS}: {len(old)} labels")


def scoreboard(csv_path):
    labels = load_labels()
    out = []
    for pair in PAIRS:
        files = sorted(glob.glob(str(ROOT / PAIRS[pair])))
        for p in files:
            items = json.load(open(p, encoding="utf-8"))["items"]
            good = bad = dup = unknown = 0
            for x in items:
                if x.get("kind") in ("правило", "завдання") and x.get("fact"):
                    m = labels.get((LABEL_OF[pair], key(x["ts"], x["text"])))
                    good += m == "+"
                    bad += m == "-"
                    dup += m == "="
                    unknown += m is None
            total = good + bad + dup + unknown
            # Точність рахується лише по розміченому; нерозмічене видно окремо,
            # щоб нове формулювання не покращило число тишею. Дубль у числі
            # точності - не потрібен: читач бачить той самий факт двічі.
            known = good + bad + dup
            prec = round(good / known, 3) if known else ""
            out.append({"pair": pair, "seed": re.search(r"s(\d+)\.json$", p).group(1),
                        "rows": total, "needed": good, "junk": bad, "dup": dup,
                        "unlabelled": unknown, "precision": prec})
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    for r in out:
        print(f"{r['pair']:5} s{r['seed']}  rows {r['rows']:3}  need {r['needed']:3}  "
              f"junk {r['junk']:3}  dup {r['dup']:3}  unlabelled {r['unlabelled']:3}  "
              f"precision {r['precision']}")
    if any(r["unlabelled"] for r in out):
        print("! є нерозмічені рядки - число неповне, зроби --sheet і розміть")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", choices=list(PAIRS), help="зробити аркуш для розмітки")
    ap.add_argument("--collect", choices=list(PAIRS), help="забрати мітки з аркуша в еталон")
    ap.add_argument("--csv", default=str(ROOT / "results" / f"precision_{time.strftime('%Y-%m-%d')}.csv"))
    a = ap.parse_args()
    if a.sheet:
        sheet(a.sheet)
    elif a.collect:
        save_labels({(LABEL_OF[a.collect], k): m for k, m in collect(a.collect).items()})
    else:
        scoreboard(a.csv)


if __name__ == "__main__":
    main()
