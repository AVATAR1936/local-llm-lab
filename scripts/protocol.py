# -*- coding: utf-8 -*-
"""Punkt 1.3: zapys pary -> protokol. Dva vydy z odnykh danykh.

Korotkyj vyd - tema i spysok "Vazhlyve". Povnyj - te zh plyus rozdily za
khodom pary z tajmkodamy. Dani odni j ti sami, riznycya lyshe u vidmalyovci:
tak vyrisheno v 1.3 za literaturoyu (arXiv 2307.15793 - korystuvacham
potribni oba vydy).

Poryadok vyklykiv i chomu same takyj:
  1. windows()      - kod rizhe paru na vikna po 5 khv po mezhakh sehmentiv;
  2. describe()     - model' opysuye kozhne vikno (pidzaholovok i punkty);
  3. org_windows()  - yaki vikna pro organizaciyu navchannya, a ne pro
                      material: shar "Vazhlyve" shukaye lyshe v nykh
                      (tochnist' 0.16 -> 0.44-0.58 na predmetnij pari);
  4. group()        - vikna v rozdily, odnym vyklykom nad usima
                      pidzaholovkamy (vikno za viknom model' tyahne v
                      "ta sama tema" i vsya para stayet odnym rozdilom);
  5. classify()     - dva prokhody po kandydatakh organizacijnykh vikon.

Kod pereviryaye te, shcho mozhna pereviryty bez chytannya: tajmkody
spravzhni, rozdily pokryvayut' paru bez velykykh dirok, vidpovid' ye na
kozhne vikno i na kozhnoho kandydata. Vse, shcho ne zijshlosya, pyshet'sya
v "perevirky" - movchky ne huByt'sya nichoho.

    python scripts/protocol.py --transcript out/asr/whisper-large-v3+fb+vad-p260216.txt
    python scripts/protocol.py --audio "E:\\Video\\...\\para.mkv" --tag=-p260216
"""
import argparse, json, pathlib, subprocess, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import llm, protocol_chapters as chapters, protocol_numbers as numbers

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "protocol"
ASR_OUT = ROOT / "out" / "asr"
ASR_NAME = "whisper-large-v3+fb+vad"      # завжди з --fallback --vad, див. CLAUDE.md


def transcribe(audio, tag):
    """Zapys -> stenohrama cherez asr-run.py. Okremym procesom, a ne importom:
    imya fajlu z defisom ne importuyet'sya, a peremenovuvaty joho - chuzha
    pravka do chuzhoho zamiru."""
    out = ASR_OUT / f"{ASR_NAME}{tag}.txt"
    if out.exists():
        print(f"  стенограма вже є: {out.name}", flush=True)
        return out
    cmd = [sys.executable, str(ROOT / "scripts" / "asr-run.py"), "--only", "whisper-large-v3",
           "--fallback", "--vad", "--audio", str(audio), f"--tag={tag}"]
    print("  " + " ".join(cmd[1:]), flush=True)
    subprocess.run(cmd, check=True)
    if not out.exists():
        sys.exit(f"asr-run не створив {out}")
    return out


def build(transcript, seed=42, margin=0):
    """({dani protokolu}, {perevirky}) - use, shcho potribno dlya oboh vydiv.

    margin - sekundy zakhoplennya za mezheyu organizacijnoho vikna, dyv.
    chapters.org_ranges(): 0 - umova, na yakij zmiryana tochnist' rozdilu."""
    checks, t0 = {}, time.perf_counter()

    wins = chapters.windows(transcript)
    desc, d_st = chapters.describe(wins, seed)
    checks["вікон"] = len(wins)
    checks["вікон без опису"] = d_st["missing_after"]

    org, o_st = chapters.org_windows(wins, desc, seed)
    checks["організаційних вікон"] = f"{len(org)}/{len(wins)} {sorted(org)}"
    checks["вікон, про які модель промовчала"] = o_st["silent"]

    title, starts, g_st = chapters.group(wins, desc, seed)
    out = chapters.assemble(title, wins, desc, starts)
    ch = chapters.check(transcript, out)
    checks["розділів"] = ch["chapters"]
    checks["вигадані таймкоди"] = ch["fake_ts"]
    checks["розділи по порядку"] = ch["in_order"]
    checks["найбільша діра, хв"] = ch["max_gap_min"]
    checks["діапазони без ремонту"] = g_st["valid_before_repair"]

    ms = numbers.mentions(transcript)
    kept = numbers.within(ms, chapters.org_ranges(wins, org, transcript, margin))
    got, c_st = numbers.classify(kept, seed)
    rows = numbers.section_rows(kept, got)
    checks["кандидатів"] = f"{len(ms)} -> {len(kept)}"
    checks["без відповіді після повтору"] = c_st["missing_after"]
    checks["рядків «Важливе»"] = len(rows)

    checks["викликів моделі"] = d_st["calls"] + 1 + 1 + c_st["calls"]
    checks["секунд"] = round(time.perf_counter() - t0, 1)
    data = {"title": title or out["title"], "important": rows, "chapters": out["chapters"],
            "windows": [{"id": w["id"], "start": w["start"]} for w in wins],
            "org": sorted(org), "seed": seed, "margin": margin, "checks": checks}
    return data, checks


def render_short(d):
    """Tema i "Vazhlyve". Porozhnij rozdil ne vyvodyt'sya vzahali - ce rishennya
    1.3: porozhnye "nemaye" v protokoli lyshe zajmaye ryadok."""
    lines = [f"# {d['title']}", ""]
    if d["important"]:
        lines += ["## Важливе", ""] + [_row(r) for r in d["important"]]
    else:
        # Не "немає" під заголовком, а окремий рядок: у короткому виді, де
        # більше нічого немає, порожній розділ виглядає як поламаний скрипт.
        lines.append("Організаційного в цій парі не прозвучало.")
    return "\n".join(lines).rstrip() + "\n"


def render_full(d):
    """Te zh plyus rozdily za khodom pary. "Vazhlyve" spereda: ce spysok
    "ne propustyty", a ne dodatok do rozdiliv."""
    lines = [f"# {d['title']}", ""]
    if d["important"]:
        lines += ["## Важливе", ""] + [_row(r) for r in d["important"]] + [""]
    lines += ["## За ходом пари", ""]
    for c in d["chapters"]:
        lines.append(f"### [{c['start']}] {c['title']}")
        for s in c["sections"]:
            lines.append(f"**[{s['start']}] {s['title']}**")
            lines += [f"- {p}" for p in s["points"]]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _row(r):
    ts = r["ts"] if r["ts_end"] == r["ts"] else f"{r['ts']}–{r['ts_end']}"
    line = f"- [{ts}] {r['fact']}"
    return line + (f" — дослівно: «{r['quote']}»" if r["quote"] else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", help="готова стенограма (out/asr/*.txt)")
    ap.add_argument("--audio", help="запис пари; буде розпізнано через asr-run.py")
    ap.add_argument("--tag", default="", help="суфікс імен для --audio, напр. --tag=-p260216")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--margin", type=int, default=0,
                    help="секунд захоплення за межею організаційного вікна")
    ap.add_argument("--name", default=None, help="ім'я виводу; типово - ім'я стенограми")
    a = ap.parse_args()
    if not (a.transcript or a.audio):
        sys.exit("потрібно --transcript або --audio")

    path = pathlib.Path(a.transcript) if a.transcript else transcribe(pathlib.Path(a.audio), a.tag)
    text = path.read_text(encoding="utf-8")
    name = a.name or path.stem

    try:
        data, checks = build(text, a.seed, a.margin)
    except llm.ContextOverflow as e:
        sys.exit(f"вікно моделі: {e}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.short.md").write_text(render_short(data), encoding="utf-8")
    (OUT / f"{name}.full.md").write_text(render_full(data), encoding="utf-8")
    (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in checks.items():
        print(f"  {k}: {v}", flush=True)
    print(f"  -> {OUT / name}.short.md / .full.md / .json", flush=True)


if __name__ == "__main__":
    main()
