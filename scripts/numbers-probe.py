# -*- coding: utf-8 -*-
"""Punkt 0.11 -> 1.3: kudy znykayut' chysla z rozdilu "Pravyla i cyfry".

Etalon - 23 fakty pravyl kursu z hodynnoyi lekciyi (baly, stroky, kil'kosti),
vypysani vruchnu z kozhnoho chysla stenohramy. Fonovi chysla (skil'ky lyudej
u chati, nomer audytoriyi, opytuvannya) do etalona ne vkhodyat': yikh propusk
- ne pomylka. Kozhen fakt - shablon; zbih shukayet'sya okremo v rozdili 5 i v
usomu protokoli, bo "vypav z rozdilu" i "vypav zovsim" - rizni khvoroby.

    python scripts/numbers-probe.py --variant full --seeds 1 2 3 4 5 6
Vyhid: out/numbers/<variant>__s<seed>.md (u git ne jde - tam imena),
results/numbers_<data>.csv (lyshe id faktiv i 0/1).
"""
import argparse, csv, json, pathlib, re, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRANSCRIPT = ROOT / "data" / "transcripts" / "lecture_long_65min.txt"
OUT = ROOT / "out" / "numbers"
MODEL = "gemma4:12b"

# Той самий промпт, що в раундах 0.6-0.8 (verify.ps1), дослівно.
PROTOCOL_PROMPT = """Ти складаєш протокол зустрічі за стенограмою. Пиши українською.

Обов'язкові розділи, саме в цьому порядку:
1. Тема - один рядок.
2. Учасники - лише ті, хто справді говорив у стенограмі.
3. Згадані - люди, підрозділи й ролі, про яких говорили, але які не виступали.
4. Рішення - що вирішено, по пунктах.
5. Правила і цифри - усі бали, дати, строки, кількості, назви файлів, шаблонів і колонок, що прозвучали. Нічого не округлювати й не переформульовувати.
6. Питання без відповіді - те, що прозвучало, але не було вирішено.

Правила:
- Спирайся лише на стенограму. Нічого не додавай від себе.
- Якщо строк названо відносно ("наступного тижня"), запиши його так, як сказано, і постав "(?)".
- Якщо розділ порожній, напиши "немає".

СТЕНОГРАМА:
"""

# Окремий прохід лише по числах: без протоколу навколо і без відбору.
# Перевіряє, чи числа губляться через відбір і тісноту в одному списку.
NUMBERS_PROMPT = """Випиши зі стенограми всі числа, що прозвучали: бали, дати, строки, кількості, відсотки, роки, номери.
Кожне число - окремим рядком, у порядку появи, у форматі:
[таймкод] число - що воно означає, словами стенограми.

Правила:
- Нічого не пропускай, навіть якщо число здається неважливим.
- Не округлюй, не підсумовуй і не виводь нових чисел, яких не було сказано.
- Якщо одне й те саме число сказано кілька разів про одне й те саме, запиши один раз.
- Якщо сказане суперечить сказаному раніше, запиши обидва варіанти і познач "(суперечність)".

СТЕНОГРАМА:
"""

VARIANTS = {"full": PROTOCOL_PROMPT, "numbers": NUMBERS_PROMPT}

D = r"\s*(?:-|–|—|по|до)\s*"          # діапазон: 17-29, 17 по 29, 17 до 29
FACTS = {
    "F01_labs_total_7":     r"(?<!\d)7\s*(?:лаб|лабораторн)|лаб\w*(?:\s*робіт)?\s*[:–-]\s*7(?!\d)",
    "F02_lab_10pts":        r"(?:лаб|кожн)\w*[^.\n]{0,60}(?<!\d)10\s*бал|(?<!\d)10\s*бал\w*[^.\n]{0,40}(?:лаб|кожн)",
    "F03_optional_6_7":     r"(?<!\d)(?:№\s*)?6\s*(?:і|та|й|,|/)\s*(?:№\s*)?7(?!\d)",
    "F04_max_80":           r"(?<!\d)80\s*бал|макс\w*[^.\n]{0,60}(?<!\d)80(?!\d)",
    "F05_labs_70":          r"(?<!\d)70\s*бал",
    "F06_test_15":          r"тест\w*[^.\n]{0,40}(?<!\d)15\s*бал|(?<!\d)15\s*бал\w*[^.\n]{0,30}тест",
    "F07_tests_30":         r"тест\w*[^.\n]{0,40}(?<!\d)30\s*бал|(?<!\d)30\s*бал\w*[^.\n]{0,30}тест",
    "F08_bonus_upto_5":     r"до\s*5\s*бал",
    "F09_slides_5_7":       r"(?<!\d)5\s*[-–]\s*7\s*слайд|слайд\w*[^.\n]{0,40}(?<!\d)5\s*[-–]\s*7(?!\d)",
    "F10_extra_test_5":     r"тест\w*[^.\n]{0,60}(?<!\d)5\s*бал|(?<!\d)5\s*бал\w*[^.\n]{0,60}тест",
    "F11_att1_min_15":      r"(?:не\s*менше|мінімум|щонайменше|мін\.)\s*15",
    "F12_att2_30":          r"атестац\w*[^.\n]{0,60}(?<!\d)30\s*бал|(?<!\d)30\s*бал\w*[^.\n]{0,60}атестац",
    "F13_att2_4labs":       r"(?<!\d)4\s*(?:лаб|лабораторн)|чотири\s*лаб",
    "F14_credit_5labs":     r"(?<!\d)5\s*(?:обов\S*\s*)?(?:лаб|лабораторн)",
    "F15_semester_4mo":     r"(?<!\d)4\s*місяц",
    "F16_att1_17_29_mar":   r"17(?:\s*берез\w*)?(?:" + D + r"|[^.\n]{0,25}закінч\w*\s*)29",
    "F17_deadline_2359":    r"23[:.]59",
    "F18_test1_18_or_25":   r"18(?:-?го)?[\s,]*(?:або|чи|/|,)[\s,]*(?:або\s*)?25",
    "F19_att2_5_17_may":    r"(?<!\d)5(?:\s*трав\w*)?" + D + r"17",
    "F20_test2_6_or_13":    r"(?<!\d)6(?:-?го)?[\s,]*(?:або|чи|/|,)[\s,]*(?:або\s*)?13",
    "F21_credit_26_to_7":   r"26(?:\s*трав\w*)?" + D + r"7\s*черв",
    "F22_retake_23_28":     r"23" + D + r"28",
    "F23_avg_7_9":          r"(?<!\d)7\s*[-–]\s*9(?!\d)",
}


def norm(t):
    t = t.lower().replace("’", "'").replace("ʼ", "'").replace("*", "")
    return re.sub(r"[ \t]+", " ", t)


def section5(t):
    """Tekst mizh zaholovkom "Pravyla i cyfry" i nastupnym rozdilom."""
    m = re.search(r"правила\s+і\s+цифри(.*?)(?:\n[#\s\d.]*питання\s+без\s+відповіді|\Z)", t, re.S)
    return m.group(1) if m else ""


def ask(prompt, seed, temperature, predict):
    body = {"model": MODEL, "prompt": prompt, "stream": False, "think": False,
            "options": {"num_ctx": 32768, "temperature": temperature, "top_p": 0.9, "top_k": 40,
                        "repeat_penalty": 1.0, "seed": seed, "num_predict": predict}}
    req = urllib.request.Request("http://localhost:11434/api/generate",
                                 data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    return json.load(urllib.request.urlopen(req, timeout=1800))


def score(text, whole=False):
    t = norm(text)
    s5 = t if whole else section5(t)
    return {f: (int(bool(re.search(p, s5))), int(bool(re.search(p, t)))) for f, p in FACTS.items()}


def foreign_numbers(text, transcript, whole=False):
    """Chysla z rozdilu, yakykh nemaye u stenohrami: vyhadani abo vyvedeni
    (9 100 zamist' 9 060, "100 baliv" yak suma). Tajmkody ne rakhuyut'sya."""
    body = transcript.split("\n", 3)[3]
    have = set(re.findall(r"\d+", re.sub(r"\[\d\d:\d\d:\d\d\]", " ", body)))
    have |= {"20" + n for n in have if len(n) == 2}    # "23-го року" -> 2023 - не вигадка
    t = norm(text)
    s5 = re.sub(r"\[?\d\d:\d\d(?::\d\d)?\]?", " ", t if whole else section5(t))
    # Однозначні не рахуємо: у мові вони звучать словами ("один тест").
    return sorted({n for n in re.findall(r"\d+", s5) if n not in have and int(n) >= 10}, key=int)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="full", choices=list(VARIANTS))
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5, 6])
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--predict", type=int, default=3000)
    ap.add_argument("--csv", default=str(ROOT / "results" / f"numbers_{time.strftime('%Y-%m-%d')}.csv"))
    ap.add_argument("--rescore", action="store_true", help="only rescore saved outputs")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    transcript = TRANSCRIPT.read_text(encoding="utf-8")
    new = not pathlib.Path(args.csv).exists()
    with open(args.csv, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["variant", "temperature", "seed", "fact", "in_section", "in_doc",
                        "out_tokens", "tps"])
        for seed in args.seeds:
            path = OUT / f"{args.variant}__t{args.temperature}__s{seed}.md"
            if args.rescore:
                text, meta = path.read_text(encoding="utf-8"), {}
            else:
                r = ask(VARIANTS[args.variant] + transcript, seed, args.temperature, args.predict)
                text = r["response"]
                meta = {"out_tokens": r.get("eval_count"),
                        "tps": round(r["eval_count"] / (r["eval_duration"] / 1e9), 1) if r.get("eval_duration") else ""}
                path.write_text(text, encoding="utf-8")
            whole = args.variant != "full"
            sc = score(text, whole)
            foreign = foreign_numbers(text, transcript, whole)
            for fact, (sec, doc) in sc.items():
                w.writerow([args.variant, args.temperature, seed, fact, sec, doc,
                            meta.get("out_tokens", ""), meta.get("tps", "")])
            w.writerow([args.variant, args.temperature, seed, "_foreign_count", len(foreign), len(foreign),
                        meta.get("out_tokens", ""), meta.get("tps", "")])
            f.flush()
            print(f"seed {seed}: section {sum(s for s, _ in sc.values())}/{len(FACTS)}  "
                  f"doc {sum(d for _, d in sc.values())}/{len(FACTS)}  tokens {meta.get('out_tokens')}  "
                  f"foreign {foreign}", flush=True)


if __name__ == "__main__":
    main()
