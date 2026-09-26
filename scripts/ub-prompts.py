"""Verkhnya mezha konvejera (UB-konvejer): prompty ZI ZBEREZHENOHO prohonu.

Chomu ne zanovo: vybir organizacijnykh vikon - vyklyk modeli, i pry tomu samomu
zerni dvi sprobi daly 62 i 54 kandydaty (3e). Shchob verkhnya mezha mirayalas'
na TOMU SAMOMU nabori, yakyj bachyla gemma, kandydaty berutsya z items
zberezhenoho prohonu, a ne peraobchyslyuyutsya.

  python scripts/ub-prompts.py out/numbers/l2__org60__extract__t0.2__s1.json
"""
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import protocol_numbers as pn

FIELDS = ("id", "ts", "text", "prev", "num", "task", "orgw")
PASSES = (("rules", "RULES_PROMPT", lambda m: m.get("num")),
          ("tasks", "TASKS_PROMPT", lambda m: m.get("task")),
          ("cond", "COND_PROMPT",
           lambda m: m.get("orgw") and not m.get("num") and not m.get("task")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", help="out/numbers/<...>.json - zberezhenyj prohon")
    ap.add_argument("--out", default=None, help="katalog dlya promptiv")
    ap.add_argument("--batch", type=int, default=pn.BATCH)
    a = ap.parse_args()

    run = pathlib.Path(a.run)
    d = json.loads(run.read_text(encoding="utf-8"))
    ms = [{k: it.get(k) for k in FIELDS} for it in d["items"]]
    gemma = {it["id"]: {"kind": it.get("kind"), "fact": it.get("fact", "")}
             for it in d["items"] if "kind" in it}

    out = pathlib.Path(a.out or ROOT / "out" / "ub" / run.stem)
    out.mkdir(parents=True, exist_ok=True)
    (out / "candidates.json").write_text(
        json.dumps({"run": run.name, "items": ms, "gemma": gemma},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{run.name}: {len(ms)} candidates")
    for tag, prompt_name, pick in PASSES:
        items = [m for m in ms if pick(m)]
        if not items:
            print(f"  {tag}: 0 - pass not called")
            continue
        num = {m["id"]: i + 1 for i, m in enumerate(items)}
        prompt = getattr(pn, prompt_name)
        for k in range(0, len(items), a.batch):
            part = items[k:k + a.batch]
            path = out / f"{tag}-{k // a.batch + 1}.txt"
            path.write_text(prompt + pn._render(part, num), encoding="utf-8")
            print(f"  {tag}-{k // a.batch + 1}: {len(part)} sentences -> {path}")


if __name__ == "__main__":
    main()
