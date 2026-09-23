# -*- coding: utf-8 -*-
"""Zavdannya 1.1: rozbizhnosti chotyrokh holosiv - shcho slukhaty dlya etalona.

Vyrivnyuye chotyry rozshyfrovky vidnosno opornoyi (Whisper, u neyi ye
taymkody sliv), znakhodyt' misciya, de holosy rozijshlysya, i zbyraye yikh u
spysok dlya proslukhovuvannya z taymkodamy. Ce ne WER i ne otsinka tochnosti:
ce perelik mists, de pravdu vyrishuye vukho.

Normalizaciya odnakova dlya vsikh (dyv. plan, klasy uhod):
  klas 1 (oformlennya) - registr, znaky, latynka terminiv -> odne napysannya
  klas 2 (shcho vvazhaty slovom) - odnoznachni slova-parazyty i pidryad
          povtory prybyrayutsya z usikh tekstiv

Zapusk:
    & "D:\\Local Cluster\\.venv\\Scripts\\python.exe" "D:\\Local Cluster\\scripts\\consensus.py" --large <nazva> --turbo <nazva>
"""
import argparse, collections, difflib, json, pathlib, re

ROOT = pathlib.Path(r"D:\Local Cluster")
ASR = ROOT / "out" / "asr"
GEMINI = ROOT / "data" / "transcripts" / "gemini_2026-09-16.txt"
OUT = ROOT / "out" / "consensus"

APOS = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "‘": "'"})

# Клас 1. Латиниця термінів -> одне кириличне написання. Словник лише для
# цього заміру (див. план): у продукт він не йде. Спотворені кириличні
# варіанти сюди навмисно не внесені — це помилки, їх має бути видно.
LATIN = {
    "start": "старт", "stop": "стоп", "continue": "контінію", "good": "гуд",
    "bad": "бед", "fix": "фікс", "peer": "пір", "review": "рев'ю",
    "action": "екшен", "items": "айтеми", "item": "айтем", "item-и": "айтеми",
    "action-items": "екшен айтеми", "peer-review": "пір рев'ю",
    "breakout": "брейкаут", "agile": "аджайл", "demo": "демо",
}

# Клас 2. Лише однозначні паразити й вигуки: «так» і «тобто» лишаються —
# вони бувають змістовними, і списком цього не розрізнити.
FILLERS = {"ну", "типу", "угу", "ага", "а-а", "е-е", "м-м", "мм", "ем", "еее",
           "mm-hmm", "uh", "um", "хм"}

WORD = re.compile(r"[\w']+(?:-[\w']+)*")


def norm_words(text):
    text = text.translate(APOS).lower()
    out = []
    for w in WORD.findall(text):
        w = w.strip("'")
        if not w:
            continue
        for part in LATIN.get(w, w).split():
            if part in FILLERS:
                continue
            if out and out[-1] == part:  # «як як як» -> «як»
                continue
            out.append(part)
    return out


def load_whisper(name):
    """Opornyj holos: slova z taymkodamy.

    Slova berutsya z tekstu segmenta, a ne z poslivnykh taymkodiv: Whisper
    rizhe «контін'ю» na «контін» + «'ю». Chas slova interpolyuyetsya
    vseredyni segmenta - dlya taymkodu proslukhovuvannya tochnist dostatnya.
    """
    d = json.loads((ASR / f"{name}.json").read_text(encoding="utf-8"))
    words, times = [], []
    for s in d["segments_data"]:
        ws = norm_words(s["text"])
        for k, n in enumerate(ws):
            if words and words[-1] == n:
                continue
            words.append(n)
            times.append(s["start"] + (s["end"] - s["start"]) * k / max(len(ws), 1))
    return words, times


def load_text(path, gemini=False):
    text = path.read_text(encoding="utf-8-sig")
    if gemini:
        text = re.sub(r"\[cite:[^\]]*\]", " ", text)
        text = re.sub(r"(?m)^[^«\n]{1,80}?:\s*«", " ", text)
    else:
        text = re.sub(r"(?m)^#.*$", " ", text)
        text = re.sub(r"\[\d\d:\d\d:\d\d\]", " ", text)
    return norm_words(text)


def align(pivot, other):
    """Dlya kozhnoyi pozyciyi opornoho - shcho skazav inshyj holos.

    Vstavky inshoho holosu (slova, yakykh nemaye v opornomu) prypysuyutsya
    najblyzhchij poperednij pozyciyi, shchob ne zahubyty yikh.
    """
    slot = [[] for _ in pivot]
    sm = difflib.SequenceMatcher(None, pivot, other, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                slot[i1 + k].append(other[j1 + k])
        elif tag == "replace":
            # Замінений шматок цілком — у першу позицію; решта позицій ділянки
            # лишаються порожніми й теж позначаються спірними.
            slot[i1].extend(other[j1:j2])
        elif tag == "insert":
            slot[max(i1 - 1, 0)].extend(other[j1:j2])
        # delete: slot lyshayetsya porozhnim - holos ne skazav cioho slova
    return slot, sm.ratio()


def compute(large, turbo, parakeet="parakeet-tdt-0.6b-v3", gap=2.0):
    """Vyrivnyuvannya i dilyanky - okremo vid druku, shchob wer.py buduvav
    ti sami dilyanky, shcho bachyv slukhach."""
    pivot, times = load_whisper(large)
    voices = {
        "turbo": load_text(ASR / f"{turbo}.txt"),
        "parakeet": load_text(ASR / f"{parakeet}.txt"),
        "gemini": load_text(GEMINI, gemini=True),
    }
    slots, ratios = {}, {}
    for n, ws in voices.items():
        slots[n], ratios[n] = align(pivot, ws)

    # Позиція спірна, якщо хоч один голос сказав там не те саме слово, що опорний.
    names = ["large"] + list(voices)
    odd_one = collections.Counter()
    disputed, to_listen = [], []
    majority = {}  # pozyciya 3:1 -> slova bilshosti
    kinds = collections.Counter()
    for i, w in enumerate(pivot):
        said = {"large": [w]}
        for n in voices:
            said[n] = slots[n][i]
        if all(said[n] == [w] for n in voices):
            continue
        disputed.append(i)
        keyed = {n: " ".join(said[n]) for n in names}
        cnt = collections.Counter(keyed.values())
        top = cnt.most_common(1)[0][1]
        if top == 3:
            # Три проти одного: більшість приймається без прослуховування.
            # Корельованість сімейства тут не шкодить: у будь-якій трійці є
            # хоча б один голос не-Whisper, бо Whisper-ів лише два.
            kinds["3:1"] += 1
            majority[i] = cnt.most_common(1)[0][0].split()
            for n in names:
                if cnt[keyed[n]] == 1:
                    odd_one[n] += 1
        else:
            kinds["2:2" if top == 2 and len(cnt) == 2 else "no majority"] += 1
            to_listen.append(i)

    # Склеюємо сусідні позиції «слухати» в ділянки для прослуховування.
    regions = []
    for i in to_listen:
        if regions and times[i] - times[regions[-1][-1]] <= gap:
            regions[-1].append(i)
        else:
            regions.append([i])

    return dict(pivot=pivot, times=times, slots=slots, ratios=ratios, names=names,
                voices=voices, disputed=disputed, to_listen=to_listen, kinds=kinds,
                majority=majority, odd_one=odd_one, regions=regions)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--large", required=True, help="output name of large-v3 run (pivot)")
    ap.add_argument("--turbo", required=True, help="output name of turbo run")
    ap.add_argument("--parakeet", default="parakeet-tdt-0.6b-v3")
    ap.add_argument("--gap", type=float, default=2.0, help="merge regions closer than N s")
    ap.add_argument("--force", action="store_true", help="overwrite disputes.txt even if it has answers")
    args = ap.parse_args()

    c = compute(args.large, args.turbo, args.parakeet, args.gap)
    pivot, times, slots, ratios, names, voices = (c[k] for k in
        ("pivot", "times", "slots", "ratios", "names", "voices"))
    disputed, to_listen, kinds, odd_one, regions = (c[k] for k in
        ("disputed", "to_listen", "kinds", "odd_one", "regions"))

    def span(ids, n):
        if n == "large":
            return " ".join(pivot[j] for j in ids)
        return " ".join(" ".join(slots[n][j]) or "·" for j in ids)

    OUT.mkdir(parents=True, exist_ok=True)
    # U disputes.txt slukhach vpysuye vidpovidi - ne zatyraty yikh movchky.
    target = OUT / "disputes.txt"
    if target.exists() and not args.force:
        body = target.read_text(encoding="utf-8").splitlines()
        answered = any(l.strip() and not l.startswith(("#", "  large", "  turbo", "  parakeet", "  gemini"))
                       for l in body)
        if answered:
            raise SystemExit(f"{target} has answers written into it; use --force to overwrite")
    lines = [f"# Rozbizhnosti: opornyj {args.large}, turbo {args.turbo}",
             f"# pozycij: {len(pivot)}, spirnykh: {len(disputed)}, slukhaty: {len(to_listen)}, "
             f"dilyanok: {len(regions)}",
             "# Tut lyshe misciya bez bilshosti 3:1 - de pravdu vyrishuye vukho.", ""]
    listen = 0.0
    for r in regions:
        t0, t1 = times[r[0]], times[r[-1]]
        listen += (t1 - t0) + 4.0  # плюс по дві секунди контексту з боків
        m, s = divmod(int(t0), 60)
        lines.append(f"## {m:02d}:{s:02d}")
        for n in names:
            lines.append(f"  {n:<9} {span(r, n)}")
        lines.append("")
    (OUT / "disputes.txt").write_text("\n".join(lines), encoding="utf-8")

    print(f"pivot words: {len(pivot)}; " + ", ".join(f"{n}={len(v)}" for n, v in voices.items()))
    print("similarity to pivot (NOT accuracy): " + ", ".join(f"{n}={r:.3f}" for n, r in ratios.items()))
    print(f"disputed positions: {len(disputed)} ({len(disputed) / len(pivot):.1%}): "
          + ", ".join(f"{k}={v}" for k, v in kinds.items()))
    print(f"to listen: {len(to_listen)} positions ({len(to_listen) / len(pivot):.1%}), regions: {len(regions)}")
    print(f"estimated listening: {listen / 60:.1f} min of 16.2")
    print("alone against three (NOT accuracy): " + ", ".join(f"{n}={odd_one[n]}" for n in names))
    print(f"written: {OUT / 'disputes.txt'}")


if __name__ == "__main__":
    main()
