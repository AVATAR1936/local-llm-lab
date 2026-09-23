# -*- coding: utf-8 -*-
r"""Zhyva rozshyfrovka z komandnoho ryadka: te same yadro, shcho j u sluzhby.

    python scripts/live-run.py --target chrome.exe --seconds 120
"""
import argparse, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_core
from live_agreement import SR


def log(*a):
    print(*a, flush=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="chrome.exe", help="process name to listen to")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--model", choices=list(live_core.MODELS), default="turbo")
    ap.add_argument("--seconds", type=float, default=0, help="0 = until Ctrl+C")
    ap.add_argument("--chunk", type=float, default=1.0, help="min new audio per cycle, s")
    ap.add_argument("--trim", type=float, default=15.0)
    ap.add_argument("--max", type=float, default=30.0, dest="max_sec", help="hard cap on buffer, s")
    ap.add_argument("--mic", action="store_true", help="record microphone as a second track")
    ap.add_argument("--no-vad", action="store_true")
    ap.add_argument("--no-prompt", action="store_true")
    ap.add_argument("--rec-dir", default=None)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    cfg = live_core.Config(target=args.target, pid=args.pid, model=args.model, chunk=args.chunk,
                           trim=args.trim, max_sec=args.max_sec, vad=not args.no_vad,
                           prompt=not args.no_prompt, mic=args.mic,
                           rec_dir=args.rec_dir, out_dir=args.out_dir, seconds=args.seconds)

    def on_words(ws):
        s = session.state()
        log(f"  t={s['audio_s']:6.1f}s lag={s['lag_s']:4.1f}s  {''.join(w['word'] for w in ws)}")

    log(f"loading {live_core.MODELS[args.model]}")
    session = live_core.LiveSession(cfg, on_words=on_words,
                                    on_event=lambda k, v: log(f"  [{k}] {v}"))
    session.start()
    log(f"recording to {session.wav}")
    try:
        while session.status in ("loading", "running"):
            time.sleep(0.3)
    except KeyboardInterrupt:
        log("stopping")
    stats = session.stop()
    log("")
    for k, v in stats.items():
        if k != "config":
            log(f"  {k}: {v}")


if __name__ == "__main__":
    main()
