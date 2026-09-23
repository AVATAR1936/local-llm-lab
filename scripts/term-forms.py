# -*- coding: utf-8 -*-
"""Zavdannya 1.1: postijnist terminiv - skilkoma formamy kozhna model zapysala termin.

Spysok terminiv uzhodzhenyj vruchnu (rozmitka kandydativ). Formy shukayutsya
po korenyakh u vsikh chotyrokh rozshyfrovkakh. Registr i vyd apostrofa ne
rakhuyutsya riznymy formamy, defis i probil - rakhuyutsya: dlya poshuku v RAG
"пір-рев'ю" i "пір рев'ю" - ce vzhe rizni tokeny.

Zapusk:
    & "D:\\Local Cluster\\.venv\\Scripts\\python.exe" "D:\\Local Cluster\\scripts\\term-forms.py"
    ... --context 2     (pokazaty kontekst form, shcho trapylys ne bilshe 2 raziv)
"""
import argparse, collections, pathlib, re

ROOT = pathlib.Path(r"D:\Local Cluster")
SOURCES = {
    # Стійка конфігурація Whisper: відкат температури + VAD (див. план).
    "large": ROOT / "out" / "asr" / "whisper-large-v3+fb+vad.txt",
    "turbo": ROOT / "out" / "asr" / "whisper-large-v3-turbo+fb+vad.txt",
    "parakeet": ROOT / "out" / "asr" / "parakeet-tdt-0.6b-v3.txt",
    "gemini": ROOT / "data" / "transcripts" / "gemini_2026-09-16.txt",
}
OUT = ROOT / "out" / "terms" / "forms.txt"

APOS = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "‘": "'"})
W = r"[\w']*"  # хвіст слова: словозміна, але не через дефіс

# Термін -> корені. Двослівні спершу шукаються цілою фразою (пробіл, дефіс
# або злито), і лише потім — окремі половинки: розірвана фраза теж є формою,
# і саме такою, що ламає пошук.
TERMS = {
    "retrospective": rf"{W}ретро{W}(?:-{W}перспектив{W})?|{W}троспектив{W}|retro{W}",
    "sprint": rf"спринт{W}|sprint{W}",
    "increment": rf"інкр[еи]мент{W}|increment{W}",
    "peer review": rf"(?:peer|пір|пи[рр])[\s-]*(?:review|рев'?ю)\w*|peer|review{W}|{W}р[е]?в'[юї]{W}|{W}ревью{W}",
    "action item": rf"(?:action|[еа]кш[е]?н)[\s-]*(?:item|айтем){W}(?:-и)?|action|[еа]кш[е]?н{W}|айтем{W}|item{W}",
    "start": rf"\bстарт{W}|\bstart\b",
    "stop": rf"\bстоп(?!ц){W}|\bstop\b",
    "continue": rf"конт[иі]н{W}|continue",
    "good": r"\bgood\b|\bгуд\b",
    "bad": r"\bbad\b|\bбед\b",
    "fix": rf"\bfix\b|\bфікс\b|\bфікси\b",
    "demo": r"\bдемо\b|\bdemo\b",
    "scrum master": rf"скр[аоу]м[\s-]*ма[йс]{W}|скр[аоу]маст{W}|scrum[\s-]*master{W}|скр[аоу]м{W}|scrum",
    "breakout room": rf"breakout[\s-]*(?:рум|room){W}(?:-и)?|breakout|брейка[ую]т{W}",
    "agile": rf"agile|[ае]джайл{W}",
    "GitHub": rf"г[іи][тд][хг]аб{W}|github{W}",
    "Telegram": rf"телеграм{W}|telegram{W}",
    "дослідник-експерт": rf"дослідник[\s-]*експерт{W}",
}


# Відмінкові закінчення відкидаються: «спринт», «спринті», «спринтом» — одне
# написання. «ю» не чіпаємо: у «контінію», «рев'ю» воно частина основи.
ENDINGS = re.compile(r"(?:-и|ами|ями|ом|ем|ів|ах|и|і|у|а)$")


def stem(form):
    return ENDINGS.sub("", form) if len(form) > 5 else form


def load(name, path):
    text = path.read_text(encoding="utf-8-sig").translate(APOS)
    if name == "gemini":
        text = re.sub(r"\[cite:[^\]]*\]", " ", text)
        text = re.sub(r"(?m)^[^«\n]{1,80}?:\s*«", " ", text)
        text = text.replace("«", " ").replace("»", " ")
    else:
        text = re.sub(r"(?m)^#.*$", " ", text)
        text = re.sub(r"\[\d\d:\d\d:\d\d\]", " ", text)
    return re.sub(r"\s+", " ", text.lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", type=int, default=2)
    args = ap.parse_args()

    texts = {n: load(n, p) for n, p in SOURCES.items()}
    names = list(SOURCES)
    lines = ["# Formy terminiv po modelyakh. Stovpchyky: " + " ".join(f"{n:>8}" for n in names), ""]
    summary = []
    for term, pat in TERMS.items():
        rx = re.compile(pat)
        forms = collections.defaultdict(collections.Counter)
        ctx = collections.defaultdict(list)
        for n, t in texts.items():
            for m in rx.finditer(t):
                f = m.group(0).strip().strip("'")
                forms[f][n] += 1
                ctx[f].append(f"{n}: ...{t[max(0, m.start() - 35):m.end() + 25]}...")
        lines.append(f"## {term}")
        for f, c in sorted(forms.items(), key=lambda kv: -sum(kv[1].values())):
            lines.append(f"  {f:<28}" + " ".join(f"{c[n]:>8}" for n in names) + f"   [{stem(f)}]")
            if sum(c.values()) <= args.context:
                for s in ctx[f]:
                    lines.append(f"      {s}")
        per_model = [len({stem(f) for f, c in forms.items() if c[n]}) for n in names]
        uses = [sum(c[n] for c in forms.values()) for n in names]
        lines.append("  " + "-" * 28 + " ".join(f"{'-' * 8}" for _ in names))
        lines.append(f"  {'spellings / uses':<28}" + " ".join(f"{f'{k}/{u}':>8}" for k, u in zip(per_model, uses)))
        lines.append("")
        summary.append((term, per_model, uses))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{'term':<20}" + "".join(f"{n:>10}" for n in names))
    for term, k, u in summary:
        print(f"{term:<20}" + "".join(f"{f'{a}/{b}':>10}" for a, b in zip(k, u)))
    extra = [sum(k[i] - 1 for _, k, u in summary if u[i]) for i in range(len(names))]
    print(f"{'extra spellings':<20}" + "".join(f"{e:>10}" for e in extra))
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
