# -*- coding: utf-8 -*-
"""Dovhyj progon sluzhby: cila para cherez toj samyj soket, shcho j rozshyrennya.

Zvuk ide v real'nomu chasi, tozh progon trvaye stil'ky, skil'ky zapys.
Shchokhvylyny v CSV: vidstavannya, bufer, slova, rizy, videopam'yat', pam'yat'
procesu sluzhby - shchob pobachyty, chy shchos' roste bez mezhi.

    python scripts/live-longrun.py "E:\\...\\para.mkv" --csv results/longrun.csv
Sluzhba maye buty vzhe pidnyata (live_service.py).
"""
import argparse, asyncio, csv, ctypes, json, os, subprocess, sys, time, urllib.request
from ctypes import wintypes

import numpy as np
import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cuda_dlls import add_nvidia_dlls
add_nvidia_dlls()
from faster_whisper import decode_audio

BASE = "127.0.0.1:8756"
SR = 16000


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
               [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize",
                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


def private_mb(pid):
    k32 = ctypes.WinDLL("kernel32")
    h = k32.OpenProcess(0x1000 | 0x0010, False, pid)   # QUERY_LIMITED_INFORMATION | VM_READ
    if not h:
        return None
    try:
        c = PMC(); c.cb = ctypes.sizeof(PMC)
        ok = ctypes.WinDLL("psapi").GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
        return round(c.PrivateUsage / 2**20) if ok else None
    finally:
        k32.CloseHandle(h)


def service_pid():
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if BASE in line and "LISTENING" in line:
            return int(line.split()[-1])
    return None


def vram_mb():
    return int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used",
                                        "--format=csv,noheader,nounits"]).split()[0])


def get(path):
    return json.load(urllib.request.urlopen(f"http://{BASE}{path}"))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--every", type=float, default=60.0)
    args = ap.parse_args()

    print("decoding", flush=True)
    x = decode_audio(args.audio, sampling_rate=SR).astype(np.float32)
    print(f"audio {len(x) / SR / 60:.1f} min", flush=True)
    pid = service_pid()
    fields = ["wall_min", "audio_s", "lag_s", "buffer_s", "words", "cycle_median_s",
              "forced_trims", "seams", "vram_mb", "service_private_mb"]
    f = open(args.csv, "w", newline="", encoding="utf-8")
    out = csv.DictWriter(f, fieldnames=fields)
    out.writeheader()
    async with websockets.connect(f"ws://{BASE}/api/live/tab?mic=0", max_size=None) as ws:
        ready = json.loads(await ws.recv())
        print("ready", ready, flush=True)
        t0 = time.perf_counter(); next_mark = 0.0
        for i in range(0, len(x), 1600):
            await ws.send(x[i:i + 1600].tobytes())
            now = time.perf_counter() - t0
            if now >= next_mark:
                s = get("/api/live")
                row = {"wall_min": round(now / 60, 2), "audio_s": s["audio_s"], "lag_s": s["lag_s"],
                       "buffer_s": s["buffer_s"], "words": s["words"],
                       "cycle_median_s": s["cycle_median_s"], "forced_trims": s["forced_trims"],
                       "seams": s["seams"], "vram_mb": vram_mb(), "service_private_mb": private_mb(pid)}
                out.writerow(row); f.flush()   # рядок одразу: падіння не з'їсть уже виміряне
                print(row, flush=True)
                next_mark += args.every
            await asyncio.sleep(max(0, t0 + (i + 1600) / SR - time.perf_counter()))
    await asyncio.sleep(5)
    run = get("/api/runs")["runs"][0]
    print("final", {k: v for k, v in run.items() if k != "config"}, flush=True)
    f.close()
    print("csv", args.csv, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
