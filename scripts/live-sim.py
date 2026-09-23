# -*- coding: utf-8 -*-
"""Zavdannya 1.2: zhyva rozshyfrovka, symulyaciya na zapysi lekciyi.

Zvuk podayetsya tak, nibyto vin ide naslupu: u moment `now` dostupno rivno
`now` sekund zapysu. Kozhen cykl LocalAgreement zajmaye spravzhnij chas
obchyslennya, i poky vin ide, zvuk nakopychuyetsya - tobto zatrymka i
vidstavannya mirayut'sya chesno, a ne "yakby karta bula mytt'yevoyu".

Na vykhodi:
  * pidtverdzhenyj tekst -> out/asr/<im'ya>.txt, WER za tym samym etalonom 1.1
  * zatrymka kozhnoho slova = moment pidtverdzhennya - kinec' slova u zapysi
  * najdovsha seriya odnakovykh sliv - shchob pomityty petlyu

Zapusk (u foni, z logom):
    & "D:\\Local Cluster\\.venv\\Scripts\\python.exe" -u "D:\\Local Cluster\\scripts\\live-sim.py" --model turbo *> "D:\\Local Cluster\\out\\asr\\live.log"
"""
import argparse, importlib.util, json, os, pathlib, statistics, sys, time, wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cuda_dlls import add_nvidia_dlls
from live_agreement import OnlineASRProcessor, SR

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "out" / "asr"
AUDIO = ROOT / "data" / "audio" / "lecture_2026-09-16.wav"
MODELS = {
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large": "Systran/faster-whisper-large-v3",
}


def log(*a):
    print(*a, flush=True)


def load_wav(path):
    with wave.open(str(path)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == SR
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def make_transcribe(model, vad):
    # Та сама прийнята конфігурація 1.1: відкат температури, VAD, beam 5.
    temperature = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]

    def transcribe(audio, prompt):
        segs, _ = model.transcribe(
            audio, language="uk", beam_size=5, word_timestamps=True,
            condition_on_previous_text=True, initial_prompt=prompt or None,
            vad_filter=vad, temperature=temperature)
        segs = list(segs)
        words = [(w.start, w.end, w.word) for s in segs if s.no_speech_prob <= 0.9 for w in (s.words or [])]
        return words, [s.end for s in segs]

    return transcribe


def longest_run(words):
    best, run, prev = 0, 0, None
    for w in words:
        w = w.strip().lower()
        run = run + 1 if w == prev else 1
        best, prev = max(best, run), w
    return best


def load_wer():
    spec = importlib.util.spec_from_file_location("wer", HERE / "wer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def score(text_path, control):
    """WER proty etalona 1.1: toj samyj shlyakh, shcho j u wer.py."""
    w = load_wer()
    c = w.cons.compute(w.LARGE, w.TURBO)
    ref, masked = w.build_reference(c, w.read_answers())
    keep = [j for j in range(len(ref)) if j not in masked]
    rows = []
    for name, path in [("offline " + control, w.cons.ASR / f"{control}.txt"), ("live", text_path)]:
        slots, _ = w.cons.align(c["pivot"], w.cons.load_text(path))
        rows.append((name,) + w.score(ref, slots, keep))
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(MODELS), default="turbo")
    ap.add_argument("--chunk", type=float, default=1.0, help="min new audio per cycle, s")
    ap.add_argument("--trim", type=float, default=15.0, help="trim audio buffer longer than N s")
    ap.add_argument("--no-prompt", action="store_true", help="do not pass committed text as initial_prompt")
    ap.add_argument("--no-vad", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", default="")
    ap.add_argument("--score-only", action="store_true", help="skip the run, score existing output")
    args = ap.parse_args()

    name = f"live-{args.model}-c{args.chunk:g}" + ("-noprompt" if args.no_prompt else "") \
        + ("-novad" if args.no_vad else "") + args.tag
    txt, js = OUT / f"{name}.txt", OUT / f"{name}.json"
    control = {"turbo": "whisper-large-v3-turbo+fb+vad", "large": "whisper-large-v3+fb+vad"}[args.model]

    if not args.score_only:
        add_nvidia_dlls()
        import ctranslate2
        from faster_whisper import WhisperModel
        ctranslate2.set_random_seed(args.seed)
        log(f"loading {MODELS[args.model]}")
        model = WhisperModel(MODELS[args.model], device="cuda", compute_type="float16")
        audio = load_wav(AUDIO)
        dur = len(audio) / SR
        proc = OnlineASRProcessor(make_transcribe(model, not args.no_vad),
                                  trim_sec=args.trim, use_prompt=not args.no_prompt)

        words, cycles, max_lag = [], [], 0.0
        now, pos = 0.0, 0
        t_start = time.perf_counter()
        while pos < len(audio):
            # Чекаємо, поки набіжить щонайменше chunk секунд нового звуку.
            now = max(now, pos / SR + args.chunk)
            end = min(int(now * SR), len(audio))
            proc.insert_audio_chunk(audio[pos:end])
            pos = end
            t0 = time.perf_counter()
            o = proc.process_iter()
            dt = time.perf_counter() - t0
            now += dt
            # Відставання: скільки звуку вже набігло, а ще не подано.
            max_lag = max(max_lag, now - pos / SR)
            cycles.append(dt)
            for b, e, t in o:
                words.append({"start": round(b, 2), "end": round(e, 2), "word": t, "at": round(now, 2)})
            if len(cycles) % 50 == 0:
                log(f"  t={pos / SR:6.1f}/{dur:.0f} s cycle {statistics.median(cycles[-50:]):.2f} s "
                    f"buf {len(proc.audio) / SR:4.1f} s lag {now - pos / SR:4.1f} s words {len(words)}")
        for b, e, t in proc.finish():
            words.append({"start": round(b, 2), "end": round(e, 2), "word": t, "at": round(now, 2)})
        wall = time.perf_counter() - t_start

        lat = sorted(w["at"] - w["end"] for w in words)
        stats = {
            "model": MODELS[args.model], "chunk": args.chunk, "trim": args.trim,
            "prompt": not args.no_prompt, "vad": not args.no_vad, "seed": args.seed,
            "audio_s": round(dur, 1), "wall_s": round(wall, 1), "cycles": len(cycles),
            "cycle_median_s": round(statistics.median(cycles), 2),
            "cycle_p90_s": round(cycles and sorted(cycles)[int(len(cycles) * 0.9)], 2),
            "max_backlog_s": round(max_lag, 1), "words": len(words),
            "latency_median_s": round(statistics.median(lat), 2),
            "latency_p90_s": round(lat[int(len(lat) * 0.9)], 2),
            "latency_max_s": round(lat[-1], 2),
            "longest_repeat": longest_run(w["word"] for w in words),
        }
        txt.write_text("".join(w["word"] for w in words).strip() + "\n", encoding="utf-8")
        js.write_text(json.dumps({"stats": stats, "words": words}, ensure_ascii=False, indent=1), encoding="utf-8")
        for k, v in stats.items():
            log(f"  {k}: {v}")

    log(f"\n{'voice':<40} {'WER':>7} {'S':>5} {'D':>5} {'I':>5} {'ref':>6}")
    for n, w, s, d, i, nref in score(txt, control):
        log(f"{n:<40} {w:>7.2%} {s:>5} {d:>5} {i:>5} {nref:>6}")


if __name__ == "__main__":
    main()
