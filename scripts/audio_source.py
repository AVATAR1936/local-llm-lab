# -*- coding: utf-8 -*-
"""Dzherelo zvuku dlya zhyvoyi rozshyfrovky: stricha z procesu, bez vtrat chasu.

Nazovni viddaye blokamy float32 16 kHz mono i nomer pershoho semplu - tobto
stricha, na yakij mozhna stavyty taimkody. Vsi dzherela (loopback procesu,
mikrofon, fajl dlya symulyaciyi) mayut' odyn i toj samyj vyhlyad, tomu sluzhba
yikh ne rozriznyaye.

Zapys na dysk vedet'sya potokom: padinnya na sorokovij khvylyni ne z'yidaye
zapysanoho.
"""
import ctypes, pathlib, queue, threading, time, wave
from ctypes import wintypes

import numpy as np

import wasapi_loopback as wl

RATE = 16000


# --- пошук процесу ----------------------------------------------------------
TH32CS_SNAPPROCESS = 0x2


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def list_processes():
    """[(pid, ppid, name)] - bez zovnishnikh zalezhnostej."""
    k32 = ctypes.WinDLL("kernel32.dll")
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        raise OSError("CreateToolhelp32Snapshot failed")
    out = []
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def created_at(pid):
    """Chas stvorennya procesu (FILETIME -> float). Potriben, shchob obraty
    holovne vikno, a ne vypadkovyj piznishyj zapusk: PID pro vik ne kazhe."""
    k32 = ctypes.WinDLL("kernel32.dll")
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    t = [wintypes.FILETIME() for _ in range(4)]
    ok = k32.GetProcessTimes(h, *[ctypes.byref(x) for x in t])
    k32.CloseHandle(h)
    if not ok:
        return None
    c = t[0]
    return ((c.dwHighDateTime << 32) | c.dwLowDateTime) / 1e7


def list_targets(name):
    """Korinni procesy z cim im'yam, vid najstarishoho. Dlya Chrome korin' -
    toj, chyj bat'ko ne Chrome: same jogo derevo mistyt' audio service, yakyj
    zvodyt' usi vkladky."""
    procs = list_processes()
    by_pid = {p: n for p, _, n in procs}
    roots = [p for p, pp, n in procs
             if n.lower() == name.lower() and by_pid.get(pp, "").lower() != name.lower()]
    out = [(p, created_at(p)) for p in roots]
    return sorted([(p, c) for p, c in out if c is not None], key=lambda x: x[1])


def find_target(name):
    t = list_targets(name)
    return t[0][0] if t else None


def alive(pid):
    k32 = ctypes.WinDLL("kernel32.dll")
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


# --- джерела ----------------------------------------------------------------
class Source:
    """Spil'nyj vyhlyad: blocks() viddaye (first_sample_index, float32 blok)."""

    def blocks(self, timeout=1.0):
        raise NotImplementedError


class ProcessLoopback(Source):
    def __init__(self, name=None, pid=None, include_tree=True, wav_path=None, on_event=None):
        self.name, self.pid = name, pid
        self.include_tree = include_tree
        self.wav_path = pathlib.Path(wav_path) if wav_path else None
        self.on_event = on_event or (lambda *a: None)
        self.q = queue.Queue()
        self.samples = 0          # скільки семплів уже випущено назовні
        self._stop = threading.Event()
        self._thread = None
        self._wav = None

    # -- службове
    def _emit(self, arr):
        idx = self.samples
        self.samples += len(arr)
        if self._wav is not None:
            self._wav.writeframes((np.clip(arr, -1, 1) * 32767).astype(np.int16).tobytes())
        self.q.put((idx, arr))

    def _pad(self, seconds):
        """Dirku v chasi zapovnyuyemo tysheyu - inakshe taimkody z'yizhdzhayut'."""
        n = int(seconds * RATE)
        if n > 0:
            self._emit(np.zeros(n, dtype=np.float32))

    def _resolve(self):
        pid = self.pid or find_target(self.name)
        return pid

    def _run(self):
        fmt = wl.make_format(wl.WAVE_FORMAT_PCM, 1, RATE, 16)
        while not self._stop.is_set():
            pid = self._resolve()
            if pid is None or not alive(pid):
                self.on_event("waiting", self.name)
                t0 = time.perf_counter()
                self._stop.wait(1.0)
                self._pad(time.perf_counter() - t0)
                continue
            try:
                client, cap, ev = wl.open_stream(pid, fmt, self.include_tree)
                client.Start()
            except Exception as e:                      # процес зник між пошуком і відкриттям
                self.on_event("open_failed", f"{pid}: {e}")
                t0 = time.perf_counter()
                self._stop.wait(1.0)
                self._pad(time.perf_counter() - t0)
                continue
            self.on_event("attached", pid)
            t_last = time.perf_counter()
            try:
                while not self._stop.is_set():
                    wl._k32.WaitForSingleObject(ev, 200)
                    got = 0
                    while True:
                        n = cap.GetNextPacketSize()
                        if not n:
                            break
                        data, nr, flags, _, _ = cap.GetBuffer()
                        if flags & wl.AUDCLNT_BUFFERFLAGS_SILENT:
                            arr = np.zeros(nr, dtype=np.float32)
                        else:
                            raw = ctypes.string_at(data, nr * 2)
                            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                        cap.ReleaseBuffer(nr)
                        self._emit(arr)
                        got += nr
                    now = time.perf_counter()
                    if got:
                        t_last = now
                    elif now - t_last > 2.0:            # потік став: процес міг померти
                        if not alive(pid):
                            raise ConnectionResetError("target gone")
                        t_last = now
            except Exception as e:
                self.on_event("detached", f"{pid}: {e}")
            finally:
                try:
                    client.Stop()
                except Exception:
                    pass

    # -- назовні
    def start(self):
        if self.wav_path:
            self.wav_path.parent.mkdir(parents=True, exist_ok=True)
            self._wav = wave.open(str(self.wav_path), "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(RATE)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._wav:
            self._wav.close()
            self._wav = None

    def blocks(self, timeout=1.0):
        while True:
            try:
                yield self.q.get(timeout=timeout)
            except queue.Empty:
                return
