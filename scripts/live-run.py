# -*- coding: utf-8 -*-
r"""Zhyva rozshyfrovka: zvuk procesu -> LocalAgreement -> pidtverdzhenyj tekst.

Dzherelo zvuku - process loopback (audio_source.ProcessLoopback), tobto
zvuk konkretnoyi programy, a ne vsijeyi systemy. Zapys vedet'sya na dysk
potokom, tekst i statystyka - poruch.

    python scripts/live-run.py --target chrome.exe --seconds 120
"""
import argparse, json, os, pathlib, statistics, sys, time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cuda_dlls import add_nvidia_dlls
import audio_source as asrc
from live_agreement import OnlineASRProcessor, SR

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODELS = {"turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
          "large": "Systran/faster-whisper-large-v3"}


def log(*a):
    print(*a, flush=True)


def make_transcribe(model, vad):
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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="chrome.exe", help="process name to listen to")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--model", choices=list(MODELS), default="turbo")
    ap.add_argument("--seconds", type=float, default=0, help="0 = until Ctrl+C")
    ap.add_argument("--chunk", type=float, default=1.0, help="min new audio per cycle, s")
    ap.add_argument("--trim", type=float, default=15.0)
    ap.add_argument("--no-vad", action="store_true")
    ap.add_argument("--no-prompt", action="store_true")
    ap.add_argument("--rec-dir", default=str(ROOT / "data" / "audio" / "live"))
    ap.add_argument("--out-dir", default=str(ROOT / "out" / "live"))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = pathlib.Path(args.rec_dir) / f"{stamp}-out.wav"

    add_nvidia_dlls()
    import ctranslate2
    from faster_whisper import WhisperModel
    ctranslate2.set_random_seed(args.seed)
    log(f"loading {MODELS[args.model]}")
    model = WhisperModel(MODELS[args.model], device="cuda", compute_type="float16")
    proc = OnlineASRProcessor(make_transcribe(model, not args.no_vad),
                             trim_sec=args.trim, use_prompt=not args.no_prompt)

    src = asrc.ProcessLoopback(name=None if args.pid else args.target, pid=args.pid or None,
                               wav_path=wav, on_event=lambda k, v: log(f"  [{k}] {v}"))
    src.start()
    log(f"recording to {wav}")

    words, cycles = [], []
    pending = []
    t0 = time.perf_counter()
    fed = 0  # семплів, відданих розпізнавачу
    try:
        while True:
            if args.seconds and time.perf_counter() - t0 > args.seconds:
                break
            got = False
            for idx, arr in src.blocks(timeout=0.2):
                pending.append(arr)
                got = True
                if sum(len(a) for a in pending) >= args.chunk * SR:
                    break
            if not got and not pending:
                continue
            n = sum(len(a) for a in pending)
            if n < args.chunk * SR:
                continue
            proc.insert_audio_chunk(np.concatenate(pending))
            pending = []
            fed += n
            c0 = time.perf_counter()
            out = proc.process_iter()
            cycles.append(time.perf_counter() - c0)
            now = time.perf_counter() - t0
            for b, e, t in out:
                words.append({"start": round(b, 2), "end": round(e, 2), "word": t, "at": round(now, 2)})
            if out:
                log(f"  t={fed / SR:6.1f}s lag={now - fed / SR:4.1f}s  {''.join(w[2] for w in out)}")
    except KeyboardInterrupt:
        log("stopping")
    finally:
        for b, e, t in proc.finish():
            words.append({"start": round(b, 2), "end": round(e, 2), "word": t,
                          "at": round(time.perf_counter() - t0, 2)})
        src.stop()

    wall = time.perf_counter() - t0
    lat = sorted(w["at"] - w["end"] for w in words) or [0]
    stats = {"model": MODELS[args.model], "target": args.pid or args.target,
             "wall_s": round(wall, 1), "audio_s": round(src.samples / SR, 1),
             "captured_vs_wall_s": round(src.samples / SR - wall, 2),
             "fed_s": round(fed / SR, 1), "cycles": len(cycles),
             "cycle_median_s": round(statistics.median(cycles), 2) if cycles else None,
             "cycle_p90_s": round(sorted(cycles)[int(len(cycles) * 0.9)], 2) if cycles else None,
             "words": len(words),
             "latency_median_s": round(statistics.median(lat), 2),
             "latency_p90_s": round(lat[int(len(lat) * 0.9)], 2),
             "latency_max_s": round(lat[-1], 2),
             "wav": str(wav)}
    (out_dir / f"{stamp}.txt").write_text("".join(w["word"] for w in words).strip() + "\n", encoding="utf-8")
    (out_dir / f"{stamp}.json").write_text(json.dumps({"stats": stats, "words": words},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
    log("")
    for k, v in stats.items():
        log(f"  {k}: {v}")


if __name__ == "__main__":
    main()
