# -*- coding: utf-8 -*-
"""Znimok seredovyshcha dlya zavdannya 1.1: chym rozpiznavaty movu.
Vyvid navmysne latynkoyu - konsol PowerShell 5.1 kalichyt kyrylytsyu.
Zapusk:  python "D:\\Local Cluster\\scripts\\asr-env.py"
"""
import sys, os, shutil, subprocess

def line(k, v):
    print(f"{k:<24} {v}")

print("=" * 60)
print("PYTHON")
print("=" * 60)
line("executable", sys.executable)
line("version", sys.version.split()[0])
line("in venv", str(sys.prefix != sys.base_prefix))

print()
print("=" * 60)
print("PACKAGES")
print("=" * 60)
try:
    import importlib.metadata as md
except ImportError:
    import importlib_metadata as md
for pkg in ["faster-whisper", "ctranslate2", "openai-whisper", "whisperx",
            "onnx-asr", "onnxruntime", "onnxruntime-gpu",
            "nemo-toolkit", "torch", "numpy", "jiwer", "av"]:
    try:
        line(pkg, md.version(pkg))
    except Exception:
        line(pkg, "-")

print()
print("=" * 60)
print("CUDA")
print("=" * 60)
try:
    import ctranslate2 as ct
    line("ctranslate2 cuda devs", ct.get_cuda_device_count())
except Exception as e:
    line("ctranslate2", f"not importable: {type(e).__name__}")
try:
    import onnxruntime as ort
    line("onnxruntime providers", ",".join(ort.get_available_providers()))
except Exception as e:
    line("onnxruntime", f"not importable: {type(e).__name__}")
smi = shutil.which("nvidia-smi")
if smi:
    try:
        out = subprocess.run([smi, "--query-gpu=name,memory.total,driver_version",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
        line("gpu", out.stdout.strip())
    except Exception as e:
        line("gpu", f"nvidia-smi failed: {e}")
else:
    line("gpu", "nvidia-smi not in PATH")

print()
print("=" * 60)
print("MODEL CACHES")
print("=" * 60)
home = os.path.expanduser("~")
for label, path in [
    ("HF_HOME env", os.environ.get("HF_HOME", "-")),
    ("hf hub cache", os.path.join(home, ".cache", "huggingface", "hub")),
    ("hf hub cache (win)", os.path.join(home, ".cache", "huggingface")),
]:
    if path != "-" and os.path.isdir(path):
        try:
            names = [d for d in os.listdir(path) if "whisper" in d.lower()
                     or "parakeet" in d.lower() or "canary" in d.lower()]
        except Exception:
            names = ["<unreadable>"]
        line(label, path + "  ->  " + (", ".join(names) if names else "no asr models"))
    else:
        line(label, path)

print()
print("=" * 60)
print("AUDIO READY")
print("=" * 60)
for f in ["lecture_2026-09-16.wav", "lecture_2026-09-16.mp3"]:
    p = os.path.join("D:\\", "Local Cluster", "data", "audio", f)
    line(f, f"{os.path.getsize(p)//1024} KB" if os.path.exists(p) else "MISSING")
