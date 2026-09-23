# -*- coding: utf-8 -*-
"""Yadro zhyvoyi rozshyfrovky: odyn cykl na vsikh spozhyvachiv.

CLI (live-run.py) i sluzhba (live_service.py) vidriznyayutsya lyshe tym, kudy
viddayut' pidtverdzheni slova. Sam cykl - tut, shchob ne buty dviyakym.
"""
import json, os, pathlib, statistics, sys, threading, time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cuda_dlls import add_nvidia_dlls
import audio_source as asrc
from live_agreement import OnlineASRProcessor, SR

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODELS = {"turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
          "large": "Systran/faster-whisper-large-v3"}
_models = {}
_models_lock = threading.Lock()


def load_model(name):
    """Model trymayetsya v pam'yati mizh seansamy: zavantazhennya - sekundy,
    a kartu vona dilyt' z gemma4, tomu druhu kopiyu trymaty ne mozhna."""
    with _models_lock:
        if name not in _models:
            add_nvidia_dlls()
            import ctranslate2
            from faster_whisper import WhisperModel
            ctranslate2.set_random_seed(0)
            _models[name] = WhisperModel(MODELS[name], device="cuda", compute_type="float16")
        return _models[name]


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


class Config:
    def __init__(self, target="chrome.exe", pid=0, model="turbo", chunk=1.0, trim=15.0,
                 max_sec=30.0, vad=True, prompt=True, mic=False,
                 rec_dir=None, out_dir=None, seconds=0.0):
        self.target, self.pid, self.model = target, pid, model
        self.chunk, self.trim, self.max_sec = chunk, trim, max_sec
        self.vad, self.prompt, self.mic = vad, prompt, mic
        self.rec_dir = pathlib.Path(rec_dir or ROOT / "data" / "audio" / "live")
        self.out_dir = pathlib.Path(out_dir or ROOT / "out" / "live")
        self.seconds = seconds

    def as_dict(self):
        d = dict(self.__dict__)
        d["rec_dir"], d["out_dir"] = str(self.rec_dir), str(self.out_dir)
        return d


class LiveSession:
    """Odyn seans: dzherelo -> LocalAgreement -> pidtverdzheni slova."""

    def __init__(self, cfg, on_words=None, on_event=None):
        self.cfg = cfg
        self.on_words = on_words or (lambda ws: None)
        self.on_event = on_event or (lambda k, v: None)
        self.id = time.strftime("%Y-%m-%d_%H-%M-%S")
        self.words, self.cycles = [], []
        self.status = "idle"
        self.attached_pid = None
        self.fed = 0
        self.t0 = None
        self._stop = threading.Event()
        self._thread = None
        self.src = self.mic_src = None
        self.proc = None
        self.wav = cfg.rec_dir / f"{self.id}-out.wav"
        self.mic_wav = cfg.rec_dir / f"{self.id}-mic.wav"

    # -- стан для показу
    def state(self):
        wall = (time.perf_counter() - self.t0) if self.t0 else 0.0
        return {"id": self.id, "status": self.status, "target": self.cfg.pid or self.cfg.target,
                "attached_pid": self.attached_pid, "model": self.cfg.model,
                "wall_s": round(wall, 1), "audio_s": round(self.fed / SR, 1),
                "lag_s": round(wall - self.fed / SR, 1) if self.t0 else 0.0,
                "buffer_s": round(len(self.proc.audio) / SR, 1) if self.proc else 0.0,
                "words": len(self.words), "mic": self.cfg.mic,
                "cycle_median_s": round(statistics.median(self.cycles), 2) if self.cycles else None,
                "forced_trims": self.proc.forced if self.proc else 0,
                "seams": self.proc.seams if self.proc else 0}

    def text(self):
        return "".join(w["word"] for w in self.words).strip()

    # -- життєвий цикл
    def start(self):
        self.status = "loading"
        self.on_event("status", self.status)
        model = load_model(self.cfg.model)
        self.proc = OnlineASRProcessor(make_transcribe(model, self.cfg.vad),
                                       trim_sec=self.cfg.trim, use_prompt=self.cfg.prompt,
                                       max_sec=self.cfg.max_sec)
        self.src = asrc.ProcessLoopback(
            name=None if self.cfg.pid else self.cfg.target, pid=self.cfg.pid or None,
            wav_path=self.wav, on_event=self._src_event)
        self.src.start()
        if self.cfg.mic:
            # Мікрофон поки лише пишеться другою доріжкою: зводити його з
            # основною за таймкодами - окремий крок, ще не зроблений.
            self.mic_src = asrc.MicSource(wav_path=self.mic_wav, on_event=self._src_event)
            self.mic_src.start()
        self.status = "running"
        self.on_event("status", self.status)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        return self

    def _src_event(self, kind, value):
        if kind == "attached":
            self.attached_pid = value
        self.on_event(kind, value)

    def _worker(self):
        self.t0 = time.perf_counter()
        pending = []
        try:
            while not self._stop.is_set():
                if self.cfg.seconds and time.perf_counter() - self.t0 > self.cfg.seconds:
                    break
                for idx, arr in self.src.blocks(timeout=0.2):
                    pending.append(arr)
                    if sum(len(a) for a in pending) >= self.cfg.chunk * SR:
                        break
                n = sum(len(a) for a in pending)
                if n < self.cfg.chunk * SR:
                    continue
                self.proc.insert_audio_chunk(np.concatenate(pending))
                pending = []
                self.fed += n
                c0 = time.perf_counter()
                out = self.proc.process_iter()
                self.cycles.append(time.perf_counter() - c0)
                now = time.perf_counter() - self.t0
                if out:
                    ws = [{"start": round(b, 2), "end": round(e, 2), "word": t, "at": round(now, 2)}
                          for b, e, t in out]
                    self.words.extend(ws)
                    self.on_words(ws)
        finally:
            if self.status == "running":
                self.status = "stopping"

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        now = (time.perf_counter() - self.t0) if self.t0 else 0.0
        if self.proc:
            tail = [{"start": round(b, 2), "end": round(e, 2), "word": t, "at": round(now, 2)}
                    for b, e, t in self.proc.finish()]
            if tail:
                self.words.extend(tail)
                self.on_words(tail)
        for s in (self.src, self.mic_src):
            if s:
                s.stop()
        self.status = "done"
        stats = self.finalize()
        self.on_event("status", self.status)
        return stats

    def finalize(self):
        lat = sorted(w["at"] - w["end"] for w in self.words) or [0]
        wall = (time.perf_counter() - self.t0) if self.t0 else 0.0
        stats = {**self.state(), "config": self.cfg.as_dict(),
                 "captured_vs_wall_s": round(self.src.samples / SR - wall, 2) if self.src else None,
                 "cycles": len(self.cycles),
                 "cycle_p90_s": round(sorted(self.cycles)[int(len(self.cycles) * 0.9)], 2) if self.cycles else None,
                 "latency_median_s": round(statistics.median(lat), 2),
                 "latency_p90_s": round(lat[int(len(lat) * 0.9)], 2),
                 "latency_max_s": round(lat[-1], 2),
                 "wav": str(self.wav), "mic_wav": str(self.mic_wav) if self.cfg.mic else None}
        self.cfg.out_dir.mkdir(parents=True, exist_ok=True)
        (self.cfg.out_dir / f"{self.id}.txt").write_text(self.text() + "\n", encoding="utf-8")
        (self.cfg.out_dir / f"{self.id}.json").write_text(
            json.dumps({"stats": stats, "words": self.words}, ensure_ascii=False, indent=1), encoding="utf-8")
        return stats


def list_runs(out_dir=None):
    out_dir = pathlib.Path(out_dir or ROOT / "out" / "live")
    runs = []
    for p in sorted(out_dir.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        runs.append({"id": p.stem, **{k: v for k, v in d.get("stats", {}).items() if k != "config"}})
    return runs


def read_run(run_id, out_dir=None):
    out_dir = pathlib.Path(out_dir or ROOT / "out" / "live")
    p = out_dir / f"{run_id}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    txt = out_dir / f"{run_id}.txt"
    d["text"] = txt.read_text(encoding="utf-8") if txt.exists() else ""
    return d
