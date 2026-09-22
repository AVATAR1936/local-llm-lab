# -*- coding: utf-8 -*-
"""Zavdannya 1.1: tri rozpiznavachi na odnomu j tomu samomu audio.

Konsol PowerShell 5.1 kalichyt kyrylytsyu, tomu sluzhbovyj vyvid latynkoyu.
Sami stenohramy pyshutsya v UTF-8 u fajly, tam kyrylytsya normalna.

Zapusk:
    & "D:\\Local Cluster\\.venv\\Scripts\\python.exe" "D:\\Local Cluster\\scripts\\asr-run.py"
    ... --only whisper-large-v3        (odna model)
    ... --audio "D:\\...\\inshe.wav"
"""
import argparse, json, os, pathlib, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cuda_dlls import add_nvidia_dlls

ROOT = pathlib.Path(r"D:\Local Cluster")
OUT = ROOT / "out" / "asr"

# Модель -> як її запускати. Ідентифікатори turbo беремо той самий, що вже
# лежить у кеші HuggingFace, щоб нічого не докачувати і не міняти умови.
MODELS = {
    "whisper-large-v3":       ("faster-whisper", "Systran/faster-whisper-large-v3"),
    "whisper-large-v3-turbo": ("faster-whisper", "mobiuslabsgmbh/faster-whisper-large-v3-turbo"),
    "parakeet-tdt-0.6b-v3":   ("onnx-asr",       "nemo-parakeet-tdt-0.6b-v3"),
}


def log(*a):
    print(*a, flush=True)


def gpu_state(tag):
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20).stdout.strip()
        log(f"  gpu [{tag}]: {out} (used MiB, total MiB, util %)")
        return out
    except Exception as e:
        log(f"  gpu [{tag}]: unavailable ({e})")
        return ""


def field(obj, *names):
    """Dostaty pershe nayavne pole - API riznykh adapteriv nazyvaye yikh po-riznomu."""
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return None


def run_faster_whisper(model_id, audio):
    from faster_whisper import WhisperModel
    log(f"  loading {model_id} (cuda, float16)")
    t0 = time.perf_counter()
    m = WhisperModel(model_id, device="cuda", compute_type="float16")
    t_load = time.perf_counter() - t0

    # Явно фіксуємо все, що впливає на вихід, щоб прогін був відтворюваним:
    #   language="uk"        - без автовизначення мови, інакше це лотерея
    #   beam_size=5          - типове значення, однакове для обох варіантів
    #   vad_filter=False     - Whisper ріже сам, своїм вікном на 30 секунд
    #   word_timestamps=True - потрібні для вирівнювання з іншими моделями
    #   temperature=0.0      - без відкатів на вищу температуру
    t0 = time.perf_counter()
    segments, info = m.transcribe(
        str(audio), language="uk", beam_size=5, vad_filter=False,
        word_timestamps=True, temperature=0.0, condition_on_previous_text=True)
    segs = []
    for s in segments:  # генератор: робота йде тут, не у виклику вище
        segs.append({
            "start": round(s.start, 3),
            "end": round(s.end, 3),
            "text": (s.text or "").strip(),
            "words": [{"start": round(w.start, 3), "end": round(w.end, 3),
                       "word": w.word} for w in (s.words or [])],
        })
    t_run = time.perf_counter() - t0
    meta = {"language": info.language, "language_probability": info.language_probability,
            "duration": info.duration}
    return segs, t_load, t_run, meta


def run_onnx_asr(model_id, audio):
    import onnx_asr
    log(f"  loading {model_id} (CUDAExecutionProvider)")
    t0 = time.perf_counter()
    model = onnx_asr.load_model(
        model_id, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    vad = onnx_asr.load_vad("silero")
    t_load = time.perf_counter() - t0

    # Parakeet не тримає годину цілком у цій збірці, тому довге аудіо ріжеться
    # силеро-VAD по паузах. Це відмінність від Whisper, і вона піде в журнал.
    t0 = time.perf_counter()
    res = model.with_vad(vad).recognize(str(audio), language="uk", pnc=True)
    t_run = time.perf_counter() - t0

    segs = []
    items = res if isinstance(res, (list, tuple)) else [res]
    for s in items:
        segs.append({
            "start": round(float(field(s, "start", "start_time") or 0.0), 3),
            "end": round(float(field(s, "end", "end_time") or 0.0), 3),
            "text": str(field(s, "text") or "").strip(),
            "words": [],
        })
    return segs, t_load, t_run, {"provider": "CUDAExecutionProvider"}


def hms(t):
    t = int(t)
    return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def write_outputs(name, model_id, audio, segs, t_load, t_run, meta, gpu_before, gpu_after):
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": name, "model_id": model_id, "audio": str(audio),
        "load_seconds": round(t_load, 2), "transcribe_seconds": round(t_run, 2),
        "segments": len(segs), "meta": meta,
        "gpu_before": gpu_before, "gpu_after": gpu_after,
        "segments_data": segs,
    }
    (OUT / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [f"# {audio.name}",
             f"# модель: {name} ({model_id})",
             f"# завантаження: {t_load:.1f} с, розпізнавання: {t_run:.1f} с",
             f"# сегментів: {len(segs)}", ""]
    for s in segs:
        if s["text"]:
            lines.append(f"[{hms(s['start'])}] {s['text']}")
    (OUT / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    words = sum(len(s["text"].split()) for s in segs)
    log(f"  done: {len(segs)} segments, {words} words, "
        f"load {t_load:.1f}s + run {t_run:.1f}s")
    return words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default=str(ROOT / "data" / "audio" / "lecture_2026-09-16.wav"))
    ap.add_argument("--only", default=None, help="run a single model by name")
    args = ap.parse_args()

    audio = pathlib.Path(args.audio)
    if not audio.exists():
        sys.exit(f"audio not found: {audio}")

    log("== dll directories ==")
    for d in add_nvidia_dlls():
        log("  " + d)

    names = [args.only] if args.only else list(MODELS)
    summary = []
    for name in names:
        if name not in MODELS:
            sys.exit(f"unknown model: {name}; known: {', '.join(MODELS)}")
        kind, model_id = MODELS[name]
        log(f"\n== {name} ==")
        before = gpu_state("before")
        t_wall = time.perf_counter()
        try:
            if kind == "faster-whisper":
                segs, tl, tr, meta = run_faster_whisper(model_id, audio)
            else:
                segs, tl, tr, meta = run_onnx_asr(model_id, audio)
        except Exception as e:
            log(f"  FAILED: {type(e).__name__}: {e}")
            summary.append((name, "FAILED", f"{type(e).__name__}: {e}"))
            continue
        after = gpu_state("after")
        words = write_outputs(name, model_id, audio, segs, tl, tr, meta, before, after)
        summary.append((name, f"{time.perf_counter() - t_wall:.1f}s",
                        f"{len(segs)} seg / {words} words"))

    log("\n== summary ==")
    for row in summary:
        log(f"  {row[0]:<26} {row[1]:<10} {row[2]}")
    log(f"\noutputs: {OUT}")


if __name__ == "__main__":
    main()
