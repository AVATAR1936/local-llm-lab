# -*- coding: utf-8 -*-
"""Zavdannya 1.1: WER tr'okh modelej po etalonu z konsensusu i vukha.

Etalon buduyetsya po pozyciyakh opornoho holosu (large-v3):
  * vsi chotyry zhodni             -> ce slovo
  * bilshist' 3:1                  -> slova bilshosti
  * dilyanka, proslukhana vukhom    -> vidpovid' slukhacha
  * odnochasne movlennya, bez vidpovidi -> vyklyucheno u VSIKH odnakovo

Termin v usikh tekstakh (i v etaloni) zvodyt'sya do odniyeyi mitky za
rehulyarkamy term-forms: roznobij napysan' mirayet'sya okremo, a tut termin
zarakhovuyet'sya yak "pochutyj / ne pochutyj". Defis dilyt'sya na slova.

Okremo: slipa rozshyfrovka pershykh pivtory khvylyn proty etalona - skil'ky
pomylyly vsi chotyry odnakovo (konsensus cioho pro sebe ne znaye).

Zapusk:
    & "D:\\Local Cluster\\.venv\\Scripts\\python.exe" "D:\\Local Cluster\\scripts\\wer.py"
"""
import importlib.util, pathlib, re, sys

import jiwer

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
ANSWERS = ROOT / "out" / "consensus" / "answers_2026-09-23.txt"
BLIND = ROOT / "out" / "consensus" / "blind_2026-09-23.txt"
LARGE, TURBO = "whisper-large-v3+fb+vad", "whisper-large-v3-turbo+fb+vad"


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cons = load_module("consensus", "consensus.py")
tf = load_module("term_forms", "term-forms.py")

# Відповіді, що є коментарем, а не розшифровкою: одночасне мовлення.
CROSSTALK = re.compile(r"два розмовника|важко зрозуміти")


def read_answers():
    """{chas zaholovka: tekst abo None}. None - vyklyuchyty dilyanku."""
    out, head, text = {}, None, []
    for line in ANSWERS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if head is not None:
                out[head] = " ".join(text) or None
            head, text = line[3:].strip(), []
        elif head and line.strip() and not line.startswith(("  large ", "  turbo ", "  parakeet ", "  gemini ")):
            t = re.sub(r"\([^)]*\)", " ", line).replace("·", " ").replace("…", " ").replace("...", " ")
            text.append(t.strip())
    if head is not None:
        out[head] = " ".join(text) or None
    return {h: (None if t and CROSSTALK.search(t) else t) for h, t in out.items()}


def canon(words):
    """Klas 1 dlya WER: terminy -> mitka, defis -> probil."""
    text = " ".join(words)
    for term, pat in tf.TERMS.items():
        text = re.sub(pat, " T_" + term.replace(" ", "_").replace("-", "_") + " ", text)
    return text.replace("-", " ").split()


def build_reference(c, answers):
    pivot, times, regions = c["pivot"], c["times"], c["regions"]
    ref = [[w] for w in pivot]
    for i, ws in c["majority"].items():
        ref[i] = list(ws)
    masked = set()
    heads = [f"{int(times[r[0]]) // 60:02d}:{int(times[r[0]]) % 60:02d}" for r in regions]
    assert set(heads) == set(answers), "regions differ from the answered file"
    for r, h in zip(regions, heads):
        ans = answers[h]
        lo, hi = r[0], r[-1]
        if ans is None:
            masked.update(range(lo, hi + 1))
            continue
        a = cons.norm_words(ans)
        # Відповідь часто ширша за спірне місце: шукаємо, де її початок і
        # кінець збігаються з сусіднім узгодженим текстом, і міняємо саме
        # цю смугу — інакше слова продублюються.
        k0, k1 = max(lo - 12, 0), min(hi + 13, len(ref))
        flat, origin = [], []
        for j in range(k0, k1):
            for w in ref[j]:
                flat.append(w)
                origin.append(j)
        blocks = [b for b in cons.difflib.SequenceMatcher(None, flat, a, autojunk=False).get_matching_blocks() if b.size]
        start, end = lo, hi
        if blocks and blocks[0].b == 0:
            start = min(start, origin[blocks[0].a])
        if blocks and blocks[-1].b + blocks[-1].size == len(a):
            end = max(end, origin[blocks[-1].a + blocks[-1].size - 1])
        for j in range(start, end + 1):
            ref[j] = []
        ref[start] = a
    return ref, masked


def voice_slots(c, name):
    if name == "large":
        return [[w] for w in c["pivot"]]
    return c["slots"][name]


def score(ref_slots, hyp_slots, keep):
    ref = canon([w for j in keep for w in ref_slots[j]])
    hyp = canon([w for j in keep for w in hyp_slots[j]])
    o = jiwer.process_words(" ".join(ref), " ".join(hyp))
    return o.wer, o.substitutions, o.deletions, o.insertions, len(ref)


def blind_words():
    text = BLIND.read_text(encoding="utf-8-sig")
    # Мітки мовців «Ім'я Прізвище:» — не мовлення, і всередині рядка теж.
    text = re.sub(r"(?:^|(?<=[.,!?]\s))[^\s:.,!?]+(?:\s[^\s:.,!?]+)?:\s", " ", text, flags=re.M)
    return cons.norm_words(text)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    c = cons.compute(LARGE, TURBO)
    answers = read_answers()
    ref, masked = build_reference(c, answers)
    keep = [j for j in range(len(ref)) if j not in masked]
    n_masked_s = sum(1 for _ in masked)

    print(f"regions: {len(c['regions'])}, excluded (crosstalk / no answer): "
          f"{sum(1 for v in answers.values() if v is None)} regions, {n_masked_s} pivot positions")
    print(f"{'voice':<10} {'WER':>7} {'S':>5} {'D':>5} {'I':>5} {'ref words':>10}")
    for n in c["names"]:
        w, s, d, i, nref = score(ref, voice_slots(c, n), keep)
        print(f"{n:<10} {w:>7.2%} {s:>5} {d:>5} {i:>5} {nref:>10}")

    # Сліпа хвилина: еталон на тому ж відрізку проти вуха з нуля.
    b = canon(blind_words())
    cut = max(j for j, t in enumerate(c["times"]) if t <= 95.0)
    window = [w for j in range(cut + 1) for w in ref[j]]
    sm = cons.difflib.SequenceMatcher(None, canon(window), b, autojunk=False)
    blk = [x for x in sm.get_matching_blocks() if x.size]
    ref_win = canon(window)[: blk[-1].a + blk[-1].size] if blk else canon(window)
    o = jiwer.process_words(" ".join(b), " ".join(ref_win))
    print(f"\nblind 0:00-1:30 vs consensus reference: WER {o.wer:.2%} "
          f"(S {o.substitutions}, D {o.deletions}, I {o.insertions}, blind words {len(b)})")
    print("  includes crosstalk stretch 0:35-1:05 that the consensus excluded - see disagreements below")
    for op in o.alignments[0]:
        if op.type != "equal":
            r = " ".join(b[op.ref_start_idx:op.ref_end_idx])
            h = " ".join(ref_win[op.hyp_start_idx:op.hyp_end_idx])
            print(f"  {op.type:<11} blind: {r:<40} consensus: {h}")


if __name__ == "__main__":
    main()
