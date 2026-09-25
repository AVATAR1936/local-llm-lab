# -*- coding: utf-8 -*-
"""Perebir zapysiv: chernovi stenohramy turbo i poshuk par potribnoho typu.

Nashcho. Typ pary z nazvy fajlu ne vydno: z chotyr'okh dohadok po metadanykh
(tryvalist', chas dnya) 2026-09-25 ne vhadano ni odniyeyi - vsi chotyry
vyyavylysya predmetnymy lekciyamy. A sharu "Vazhlyve" potribna same
organizacijna para, inakshe joho tochnist' nemozhlyvo zmiryaty.

Turbo, a ne large-v3: chernovyk dlya poshuku sliv, ne dlya zamiru. Same tak
2026-09-24 bulo znajdeno druhu lekciyu z pravylamy kursu; toj perebir ne
zberehsya, tomu tut vin skryptom.

    python scripts/scan-pairs.py --transcribe     # dovho: turbo po vsikh, u fon
    python scripts/scan-pairs.py                  # tablycya za hotovymy
"""
import argparse, collections, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RECORDS = pathlib.Path(r"E:\Видео\Записи Пар")
VIDEO = ROOT / "data" / "video"          # доданi 2026-09-25, у git не йдуть
ASR = ROOT / "out" / "asr"
TURBO = "whisper-large-v3-turbo+fb+vad"
MIN_MINUTES = 5.0            # обривки по 0.2-2.3 хв - не пари

# Уже розпізнано large-v3 і використано в замірах - переглядати не треба.
USED = {"2025-02-04 08-40-38", "2025-02-06 08-35-15", "2026-02-10 10-29-33",
        "2026-02-16 08-38-43", "2026-02-02 09-30-19", "2025-03-27 09-29-20",
        "2026-03-09 08-34-50"}

# Записи з data/video: імена довгі й кириличні, тому мітка задається явно -
# кирилиця в іменах виводу ламає консоль питона на Windows. Мітка нейтральна
# і нічого не каже про роль пари: поділ на настройку й перевірку живе в плані.
EXTRA = {
    "Комплексні системи захисту інформації_ проектування, впровадження, супровід - 2026_09_04 12_18 EEST - Recording.mp4": "-ksi260904",
    "заочКомплексні системи захисту інформації_ проектування, впровадження, супровід - 2026_09_07 10_29 EEST - Recording.mp4": "-ksi260907z",
    "Комплексні системи захисту інформації_ проектування, впровадження, супровід - 2026_09_11 12_14 EEST - Recording.mp4": "-ksi260911",
    "Практична №1.mp4": "-prac1", "Практична №2.mp4": "-prac2",
    "Практична №4.mp4": "-prac4", "Практична №5.mp4": "-prac5",
    "Практична №7.mp4": "-prac7", "Практична №8.mp4": "-prac8",
}

# Слова, за якими видно тип пари. Правка 2026-09-25: перебір збрехав двічі.
# (1) Омоніми. "Бали" й "оцінювання" на курсі про оцінку захищеності - слова
# матеріалу ("критерії оцінювання безпеки", "суб'єкт оцінювання"): 8 з 10
# збігів у ksi260904 були саме такі.
# (2) Організаційний блок може не сказати жодного слова зі старого списку: він
# говорить силабусом, формою контролю, автоматом, практикумом, дейлі - і через
# це я спершу написав, що організаційних пар у нових записах немає.
# Тому "курс" - слова, яких у предметній парі не буває, і ранжування йде за
# ними; омонімічні "бали" лишаються окремою колонкою, щоб їх було видно.
MARKS = {
    "курс":   r"силабус|сілабус|форм\w* контролю|практикум|модульн|атестац|заліку?\b|заліком|екзамен|"
              r"автоматом?\b|перездач|тім\s?лід|team\s?lead|дейл|спринт|захищат\w*\s+звіт",
    "строки": r"дедлайн|класрум|classroom|до\s+\d\d?\s*(?:бере|квіт|трав|черв|жовт|лист|груд|січ|лют)|23[:.]59",
    "дії":    r"надішл|надсил|насилайт|запишіт|зареєстр|повідом|принес|здайте|оформ",
    "задачі": r"задач|розв'яж|порахуй|обчисл|на\s+дошц|до\s+дошки|запишемо|підставл",
    "бали":   r"бал[иівьу]?\b|рейтинг|оцінюван",
}
RANK = "курс"           # за чим ранжувати: слова, яких у предметній парі не буває


def stem_tag(stem):
    """2026-02-10 10-29-33 -> -scan20260210_1029: imya vyvodu, stabil'ne."""
    d, t = stem.split(" ")
    return "-scan" + d.replace("-", "") + "_" + t[:5].replace("-", "")


def minutes(path):
    import av
    try:
        with av.open(str(path)) as c:
            return round((c.duration or 0) / 1e6 / 60, 1)
    except Exception:
        return 0.0


def records():
    """[(shlyakh, khvylyn, mitka)] - obydva dzherela razom."""
    out = []
    for f in sorted(RECORDS.iterdir()):
        if f.suffix.lower() not in (".mkv", ".mp4") or f.stem in USED:
            continue
        m = minutes(f)
        if m >= MIN_MINUTES:
            out.append((f, m, stem_tag(f.stem)))
    if VIDEO.is_dir():
        for f in sorted(VIDEO.iterdir()):
            if f.name in EXTRA:
                out.append((f, minutes(f), EXTRA[f.name]))
    return out


def transcribe(files):
    for i, (f, m, tag) in enumerate(files, 1):
        out = ASR / f"{TURBO}{tag}.txt"
        if out.exists():
            print(f"[{i}/{len(files)}] {f.stem}: вже є", flush=True)
            continue
        print(f"[{i}/{len(files)}] {f.stem} ({m} хв) -> {tag}", flush=True)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "asr-run.py"),
                        "--only", "whisper-large-v3-turbo", "--fallback", "--vad",
                        "--audio", str(f), f"--tag={tag}"], check=False)


def body(path):
    return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                     if l.strip() and not l.startswith("#"))


def where(text, pat):
    """Chastka dovzhyny, na yakij lezhat' zbihy: (pochatok, seredyna, kinec) u
    vidsotkakh. Organizacijne zbyrayet'sya na krayakh pary - ce vydno tut."""
    n = len(text) or 1
    buckets = collections.Counter()
    for m in re.finditer(pat, text, re.I):
        p = m.start() / n
        buckets["п" if p < 0.2 else ("к" if p > 0.8 else "с")] += 1
    return buckets


def table(files):
    rows = []
    for f, m, tag in files:
        path = ASR / f"{TURBO}{tag}.txt"
        if not path.exists():
            continue
        t = body(path)
        counts = {k: len(re.findall(p, t, re.I)) for k, p in MARKS.items()}
        w = where(t, MARKS[RANK])
        rows.append((counts[RANK], tag.lstrip("-"), m, counts, w, len(t)))
    rows.sort(reverse=True)
    print(f"{'запис':22} {'хв':>6} {'знак':>7}  курс строки  дії задачі бали  де курс")
    for c, stem, m, counts, w, n in rows:
        print(f"{stem:22} {m:>6} {n:>7}  {counts['курс']:>4} {counts['строки']:>6} "
              f"{counts['дії']:>4} {counts['задачі']:>6} {counts['бали']:>4}  "
              f"п{w['п']} с{w['с']} к{w['к']}")
    print(f"\nрозпізнано {len(rows)} з {len(files)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcribe", action="store_true", help="turbo по всіх записах без стенограми")
    a = ap.parse_args()
    files = records()
    if a.transcribe:
        total = round(sum(m for _, m, _t in files) / 60, 1)
        print(f"записів {len(files)}, разом {total} годин звуку", flush=True)
        transcribe(files)
    table(files)


if __name__ == "__main__":
    main()
