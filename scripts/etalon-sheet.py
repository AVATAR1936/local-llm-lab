"""Arkushi dlya etalonu VYMOH (ne rechen').

Try rezhymy:
  --pair scan20260916 --all        usi rechennya pary: chesnyj znamennyk povnoty
  --pair l2 --from-labels m        lyshe rechennya, pomicheni avtorom m (+ i =)
  --audit 20                       zherebna vybirka mitok modeli dlya pereviky

Arkush pyshetsya v data/etalon/ (poza git: tam tekst, otzhe imena).
Sluzhbovyj vyvid - latynkoyu: PowerShell 5.1 kalichyt' kyrylycyu.
"""
import argparse, hashlib, importlib.util, pathlib, random, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import protocol_numbers as pn

spec = importlib.util.spec_from_file_location("precision", ROOT / "scripts" / "precision.py")
precision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(precision)

ETALON = ROOT / "data" / "etalon"
AUDIT = ROOT / "out" / "audit"
AUDIT_SEED = 20260926
NL = chr(10)

# Pary, dodani dlya cього kola. Reshta - v precision.TRANSCRIPTS.
EXTRA = {"scan20260916": "out/asr/whisper-large-v3+fb+vad-scan20260916_1229.txt"}


def transcript_path(pair):
    if pair in EXTRA:
        return ROOT / EXTRA[pair]
    return ROOT / precision.TRANSCRIPTS[pair]


def all_sentences(pair):
    """[(ts, text, oznaka)] - USI rechennya, a ne lyshe kandydaty."""
    text = pn._norm_apos(transcript_path(pair).read_text(encoding="utf-8"))
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    out, ts = [], "00:00:00"
    for line in lines:
        for part in pn.TS.split(line):
            if pn.TS.fullmatch(f"[{part}]"):
                ts = part
                continue
            for s in pn.SENT.split(part.strip()):
                s = s.strip()
                if not s:
                    continue
                sign = ("ч" if pn.NUM.search(s) else "") + ("д" if pn.TASK.search(s) else "") \
                       + ("с" if pn.ORGW.search(s) else "")
                out.append((ts, s, sign or "-"))
    return out


HEAD_ALL = """# ЕТАЛОН ВИМОГ — {pair}, {n} речень. Розмітка вручну, до прогону моделі.
#
# Крок 1. Читаєш пару зверху донизу. Кожне речення, яке несе вимогу, помічаєш
# у першому стовпці: + вимога, = та сама вимога вже записана, - фон.
# Правила, за якими це вирішується, — docs/tz-vazhlyve.md, перевірки T1-T7.
#
# Крок 2. Кожному + даєш номер вимоги в другому стовпці: T01, T02... Двом
# реченням про одну вимогу — той самий номер. Так виражаються і дублі, і
# вимога, розтягнута на два речення.
#
# Крок 3. Унизу, в блоці ВИМОГИ, одним рядком на номер: тип, об'єкт, текст.
#
# Ознака — чим речення взяв би відбір коду: ч число, д наказ, с словник
# організаційного, - нічим (такі до моделі взагалі не доїжджають).
#
# Формат: мітка | Tnn | ключ | ознака | речення
#
"""

HEAD_TAIL = """
#
# ==================== ВИМОГИ ====================
# Tnn | тип (балл/порог/срок/действие/канал/состав) | об'єкт | текст без імен
#
"""

HEAD_LABELS = """# ГРУПУВАННЯ — {pair}, {n} рядків, помічених тобою як + або =.
#
# Мітки вже стоять, переставляти не треба. Потрібен лише номер вимоги
# в другому стовпці: T01, T02... Ті рядки, що говорять про одну вимогу,
# отримують той самий номер. Це і є перехід від речень до вимог.
#
# Формат: мітка | Tnn | ключ | речення
#
"""

HEAD_KEYS = """# СУД ПО {n} РЯДКАХ — {pair}, {name}.
#
# Ці рядки третій прохід додав до розділу, мітка на них автоматична.
# Від рішення залежить, чи йде третій прохід у protocol.py.
#
# Поміть перший символ: + вимога, - смiття, = дубль, г місце в главах.
# Правила — docs/tz-vazhlyve.md, перевірки T0-T7.
#
# Формат: твоя мітка | мітка моделі | ключ | речення
#
"""

HEAD_AUDIT = """# АУДИТ МІТОК МОДЕЛІ — {n} рядків, жереб {seed}.
#
# Ці рядки розмічені автоматично. Питання одне: мітка правильна?
# Поміч у першому стовпці: v згоден, x невірно (і постав мітку далі).
# Правила — docs/tz-vazhlyve.md.
#
# Формат: v/x | мітка моделі | пара | ключ | речення
#
"""


def sheet_all(pair):
    sents = all_sentences(pair)
    old = {k: m for (p, k), m in precision.load_labels().items() if p == pair}
    lines = []
    for ts, s, sign in sents:
        k = precision.key(ts, s)
        lines.append(f"{old.get(k, '')}\t\t{k}\t{sign}\t{s}")
    ETALON.mkdir(parents=True, exist_ok=True)
    path = ETALON / f"{pair}.requirements.txt"
    path.write_text(HEAD_ALL.format(pair=pair, n=len(sents)) + "\n".join(lines)
                    + HEAD_TAIL, encoding="utf-8")
    cand = sum(1 for _, _, sign in sents if sign != "-")
    print(f"{path}: {len(sents)} sentences, {cand} would reach the model, "
          f"{len(sents) - cand} would not")


def sheet_from_labels(pair, who):
    marks = precision.load_labels()
    who_of = precision.load_authors()
    lab = {k: (m, who_of.get((pair, k), "m")) for (p, k), m in marks.items() if p == pair}
    text = {}
    for ts, s, _ in all_sentences(pair):
        text[precision.key(ts, s)] = s
    rows = [(k, m) for k, (m, w) in sorted(lab.items()) if w == who and m in "+="]
    lines = [f"{m}\t\t{k}\t{text.get(k, '<немає в стенограмі>')}" for k, m in rows]
    ETALON.mkdir(parents=True, exist_ok=True)
    path = ETALON / f"{pair}.grouping.txt"
    path.write_text(HEAD_LABELS.format(pair=pair, n=len(rows)) + "\n".join(lines)
                    + HEAD_TAIL, encoding="utf-8")
    print(f"{path}: {len(rows)} rows by author {who}")


def sheet_audit(n):
    marks = precision.load_labels()
    who_of = precision.load_authors()
    pool = [(p, k, m) for (p, k), m in sorted(marks.items()) if who_of.get((p, k)) == "o"]
    pick = random.Random(AUDIT_SEED).sample(pool, min(n, len(pool)))
    text = {}
    for pair in sorted({p for p, _, _ in pick}):
        for ts, s, _ in all_sentences(pair):
            text[(pair, precision.key(ts, s))] = s
    lines = [f"\t{m}\t{p}\t{k}\t{text.get((p, k), '<немає в стенограмі>')}"
             for p, k, m in sorted(pick)]
    AUDIT.mkdir(parents=True, exist_ok=True)
    path = AUDIT / "sample.txt"
    path.write_text(HEAD_AUDIT.format(n=len(pick), seed=AUDIT_SEED) + "\n".join(lines) + "\n",
                    encoding="utf-8")
    byp = {}
    for p, _, _ in pick:
        byp[p] = byp.get(p, 0) + 1
    print(f"{path}: {len(pick)} rows, pool {len(pool)}, by pair " + ", ".join(
        f"{p} {c}" for p, c in sorted(byp.items())))


def sheet_keys(pair, keys, name):
    marks = precision.load_labels()
    text = {precision.key(ts, s): s for ts, s, _ in all_sentences(pair)}
    lines = []
    for k in keys:
        lines.append(f"	{marks.get((pair, k), '?')}	{k}	{text.get(k, '<немає в стенограмі>')}")
    AUDIT.mkdir(parents=True, exist_ok=True)
    path = AUDIT / f"{name}.txt"
    path.write_text(HEAD_KEYS.format(n=len(keys), pair=pair, name=name)
                    + NL.join(lines) + NL, encoding="utf-8")
    print(f"{path}: {len(keys)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--from-labels", dest="who")
    ap.add_argument("--audit", type=int, default=0)
    ap.add_argument("--keys", help="comma-separated keys for a judgement sheet")
    ap.add_argument("--name", default="judge")
    a = ap.parse_args()
    if a.keys:
        sheet_keys(a.pair, [k.strip() for k in a.keys.split(",") if k.strip()], a.name)
    elif a.audit:
        sheet_audit(a.audit)
    elif a.who:
        sheet_from_labels(a.pair, a.who)
    elif a.all:
        sheet_all(a.pair)
    else:
        ap.error("need --all, --from-labels or --audit")


if __name__ == "__main__":
    main()
