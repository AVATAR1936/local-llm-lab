"""Verkhnya mezha konvejera: velyka model' proty gemma na TOMU SAMOMU vkhodi.

Formuly ti sami, shcho v precision.scoreboard: rakhuyutsya RYADKY rozdilu pislya
skleyky, tochnist' - lyshe po rozmichenomu, dubl' u znamennyku.

  python scripts/ub-score.py out/ub/<run>/ --pair l2
"""
import argparse, importlib.util, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import protocol_numbers as pn

spec = importlib.util.spec_from_file_location("precision", ROOT / "scripts" / "precision.py")
precision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(precision)

PASSES = (("rules", "правило", lambda m: m.get("num")),
          ("tasks", "завдання", lambda m: m.get("task")),
          ("cond", "умова",
           lambda m: m.get("orgw") and not m.get("num") and not m.get("task")))


def got_from_answer(ms, answer):
    """{id: {kind, fact}} z vidpovidi za lokal'nymy nomeramy prompta."""
    got = {}
    for tag, kind, pick in PASSES:
        items = [m for m in ms if pick(m)]
        back = {i + 1: m["id"] for i, m in enumerate(items)}
        for local, fact in (answer.get(tag) or {}).items():
            oid = back.get(int(local))
            if oid is None:
                print(f"  ! {tag}: local {local} out of range ({len(items)} items)")
                continue
            if oid not in got:                    # pravylo perevazhaye, yak u classify
                got[oid] = {"kind": kind, "fact": fact.strip()}
    for m in ms:
        got.setdefault(m["id"], {"kind": "фон", "fact": ""})
    return got


def score(ms, got, pair, labels):
    by_id = {m["id"]: m for m in ms}
    good = bad = dup = unknown = other = 0
    rows = pn.section_rows(ms, got)
    for r in rows:
        marks = {labels.get((pair, precision.key(by_id[i]["ts"], by_id[i]["text"])))
                 for i in r["ids"]}
        if None in marks and not (marks - {None}):
            unknown += 1
        elif "+" in marks:
            good += 1
        elif "=" in marks:
            dup += 1
        elif "г" in marks:
            other += 1
        else:
            bad += 1
    known = good + bad + dup + other
    plus = {k for (pp, k), m in labels.items() if pp == pair and m == "+"}
    in_cand = {precision.key(m["ts"], m["text"]) for m in ms} & plus
    in_rows = {precision.key(by_id[i]["ts"], by_id[i]["text"])
               for r in rows for i in r["ids"]} & plus
    return {"rows": len(rows), "needed": good, "junk": bad, "dup": dup,
            "chapters": other, "unlabelled": unknown,
            "precision": round(good / known, 3) if known else "",
            "recall": f"{len(in_rows)}/{len(in_cand)}", "plus_pair": len(plus)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--pair", required=True, help="imya pary v precision-labels.tsv")
    a = ap.parse_args()
    d = pathlib.Path(a.dir)
    cand = json.loads((d / "candidates.json").read_text(encoding="utf-8"))
    ms, gemma = cand["items"], {int(k): v for k, v in cand["gemma"].items()}
    labels = precision.load_labels()

    print(f"{cand['run']}: {len(ms)} candidates, pair {a.pair}")
    who = {"gemma": gemma}
    for f in sorted(d.glob("answer-*.json")):
        name = f.stem.replace("answer-", "")
        who[name] = got_from_answer(ms, json.loads(f.read_text(encoding="utf-8")))
    head = f"{'':10}" + "".join(f"{k:>12}" for k in
                               ("rows", "needed", "junk", "dup", "chapters", "unlab",
                                "precision", "recall"))
    print(head)
    for name, got in who.items():
        r = score(ms, got, a.pair, labels)
        print(f"{name:10}" + "".join(f"{r[k]!s:>12}" for k in
                                     ("rows", "needed", "junk", "dup", "chapters",
                                      "unlabelled", "precision", "recall")))
    print()
    print(f"plus-labels in pair: {r['plus_pair']}, of them inside the "
          f"candidate set: {r['recall'].split('/')[1]}")


if __name__ == "__main__":
    main()
