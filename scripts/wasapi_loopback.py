# -*- coding: utf-8 -*-
r"""WASAPI process loopback: zvuk odnoho procesu (z dochirnimy) bez drajveriv.

Windows 10 2004+ dozvolyaye ActivateAudioInterfaceAsync z parametramy
PROCESS_LOOPBACK: zamist' endpointa vidkryvayetsya virtual'nyj prystrij
"VAD\Process_Loopback", a zvuk berets'ya u vkazanoho procesu. Gotovoyi
obhortky v pythoni nemaye - tut vona zroblena cherez comtypes.

Probnyk:
    python scripts/wasapi_loopback.py --pid 1234 --seconds 10 --out probe.wav
"""
import sys

sys.coinit_flags = 0  # COINIT_MULTITHREADED: колбэк активації приходить у MTA

import argparse, ctypes, pathlib, threading, time, wave
from ctypes import POINTER, byref, c_byte, c_uint, c_uint32, c_uint64, c_void_p, c_wchar_p

import comtypes
from comtypes import COMMETHOD, GUID, IUnknown, COMObject, HRESULT
from ctypes.wintypes import BOOL, DWORD, HANDLE, LPCWSTR, WORD

SR_NATIVE = None  # заповнюється після Initialize

# --- константи --------------------------------------------------------------
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = r"VAD\Process_Loopback"
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY = 0x1
WAVE_FORMAT_PCM = 1
WAVE_FORMAT_IEEE_FLOAT = 3
VT_BLOB = 65
INCLUDE_TREE, EXCLUDE_TREE = 0, 1


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", WORD), ("nChannels", WORD), ("nSamplesPerSec", DWORD),
                ("nAvgBytesPerSec", DWORD), ("nBlockAlign", WORD),
                ("wBitsPerSample", WORD), ("cbSize", WORD)]


def make_format(tag, channels, rate, bits):
    block = channels * bits // 8
    return WAVEFORMATEX(tag, channels, rate, rate * block, block, bits, 0)


class PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [("TargetProcessId", DWORD), ("ProcessLoopbackMode", ctypes.c_int)]


class ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_int), ("Loopback", PROCESS_LOOPBACK_PARAMS)]


class PROPVARIANT(ctypes.Structure):
    # vt + 3 резерви, далі об'єднання; для VT_BLOB це {ULONG cbSize; BYTE *pBlobData}.
    _fields_ = [("vt", WORD), ("r1", WORD), ("r2", WORD), ("r3", WORD),
                ("cbSize", ctypes.c_ulong), ("pad", ctypes.c_ulong), ("pBlobData", c_void_p)]


# --- інтерфейси -------------------------------------------------------------
class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Initialize",
                  (["in"], ctypes.c_int, "ShareMode"), (["in"], DWORD, "StreamFlags"),
                  (["in"], ctypes.c_int64, "hnsBufferDuration"),
                  (["in"], ctypes.c_int64, "hnsPeriodicity"),
                  (["in"], POINTER(WAVEFORMATEX), "pFormat"), (["in"], c_void_p, "AudioSessionGuid")),
        COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "pNumBufferFrames")),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(ctypes.c_int64), "phnsLatency")),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "pNumPaddingFrames")),
        COMMETHOD([], HRESULT, "IsFormatSupported",
                  (["in"], ctypes.c_int, "ShareMode"), (["in"], POINTER(WAVEFORMATEX), "pFormat"),
                  (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppClosestMatch")),
        COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppDeviceFormat")),
        COMMETHOD([], HRESULT, "GetDevicePeriod",
                  (["out"], POINTER(ctypes.c_int64), "phnsDefaultDevicePeriod"),
                  (["out"], POINTER(ctypes.c_int64), "phnsMinimumDevicePeriod")),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], HANDLE, "eventHandle")),
        COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "riid"), (["out"], POINTER(c_void_p), "ppv")),
    ]


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer",
                  (["out"], POINTER(POINTER(c_byte)), "ppData"),
                  (["out"], POINTER(c_uint32), "pNumFramesToRead"),
                  (["out"], POINTER(DWORD), "pdwFlags"),
                  (["out"], POINTER(c_uint64), "pu64DevicePosition"),
                  (["out"], POINTER(c_uint64), "pu64QPCPosition")),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "NumFramesRead")),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
    ]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetActivateResult",
                  (["out"], POINTER(HRESULT), "activateResult"),
                  (["out"], POINTER(POINTER(IUnknown)), "activatedInterface")),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = [
        COMMETHOD([], HRESULT, "ActivateCompleted",
                  (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "activateOperation")),
    ]


class IAgileObject(IUnknown):
    # Маркер без методів. Без нього ActivateAudioInterfaceAsync відповідає
    # E_ILLEGAL_METHOD_CALL: обробник мусить бути незалежним від апартаменту.
    _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
    _methods_ = []


class Handler(COMObject):
    """Об'єкт зворотного виклику: ActivateAudioInterfaceAsync асинхронний."""
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

    def __init__(self):
        super().__init__()
        self.done = threading.Event()
        self.op = None

    def ActivateCompleted(self, this, op):
        self.op = op
        self.done.set()
        return 0


_mmdevapi = ctypes.WinDLL("Mmdevapi.dll")
_ActivateAudioInterfaceAsync = _mmdevapi.ActivateAudioInterfaceAsync
_ActivateAudioInterfaceAsync.restype = HRESULT
_ActivateAudioInterfaceAsync.argtypes = [LPCWSTR, POINTER(GUID), POINTER(PROPVARIANT),
                                         c_void_p, POINTER(POINTER(IActivateAudioInterfaceAsyncOperation))]


def activate(pid, include_tree=True, timeout=5.0):
    """IAudioClient, pryv'yazanyj do procesu pid (z dochirnimy abo bez)."""
    params = ACTIVATION_PARAMS(1, PROCESS_LOOPBACK_PARAMS(pid, INCLUDE_TREE if include_tree else EXCLUDE_TREE))
    pv = PROPVARIANT()
    pv.vt = VT_BLOB
    pv.cbSize = ctypes.sizeof(params)
    pv.pBlobData = ctypes.cast(byref(params), c_void_p)

    handler = Handler()
    op = POINTER(IActivateAudioInterfaceAsyncOperation)()
    sink = handler.QueryInterface(IActivateAudioInterfaceCompletionHandler)
    hr = _ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, byref(IAudioClient._iid_),
                                      byref(pv), ctypes.cast(sink, c_void_p), byref(op))
    if hr != 0:
        raise OSError(f"ActivateAudioInterfaceAsync failed: 0x{hr & 0xFFFFFFFF:08X}")
    if not handler.done.wait(timeout):
        raise TimeoutError("ActivateCompleted never called")
    res, unk = handler.op.GetActivateResult()
    if res != 0:
        raise OSError(f"activate result: 0x{res & 0xFFFFFFFF:08X}")
    return unk.QueryInterface(IAudioClient)


# --- захоплення -------------------------------------------------------------
_k32 = ctypes.WinDLL("kernel32.dll")
_k32.CreateEventW.restype = HANDLE
_k32.CreateEventW.argtypes = [c_void_p, BOOL, BOOL, LPCWSTR]
_k32.WaitForSingleObject.argtypes = [HANDLE, DWORD]

# Формати пробуються по черзі: перший — те, що потрібно розпізнаванню.
FORMATS = [
    ("pcm16 16k mono", make_format(WAVE_FORMAT_PCM, 1, 16000, 16)),
    ("float32 48k stereo", make_format(WAVE_FORMAT_IEEE_FLOAT, 2, 48000, 32)),
    ("pcm16 48k stereo", make_format(WAVE_FORMAT_PCM, 2, 48000, 16)),
    ("float32 44.1k stereo", make_format(WAVE_FORMAT_IEEE_FLOAT, 2, 44100, 32)),
]


def open_stream(pid, fmt, include_tree=True, buffer_ms=200):
    client = activate(pid, include_tree)
    flags = AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
    client.Initialize(AUDCLNT_SHAREMODE_SHARED, flags, buffer_ms * 10000, 0, byref(fmt), None)
    ev = _k32.CreateEventW(None, False, False, None)
    client.SetEventHandle(ev)
    raw = client.GetService(byref(IAudioCaptureClient._iid_))
    cap = ctypes.cast(raw, POINTER(IAudioCaptureClient))
    return client, cap, ev


def probe_formats(pid, include_tree=True):
    """Yakyj format prijmaye process loopback dlya cioho pid."""
    for name, fmt in FORMATS:
        try:
            client, cap, ev = open_stream(pid, fmt, include_tree)
        except Exception as e:
            print(f"  {name:22} -> {e}")
            continue
        print(f"  {name:22} -> OK, buffer {client.GetBufferSize()} frames")
        client.Stop()
        return name, fmt
    return None, None


def capture(pid, seconds, fmt, include_tree=True):
    """Povertaye (bytes, blockAlign, statystyka). Tysha dobudovuyetsya nulyamy."""
    client, cap, ev = open_stream(pid, fmt, include_tree)
    block = fmt.nBlockAlign
    chunks, frames, silent_frames, discont = [], 0, 0, 0
    client.Start()
    t_end = time.perf_counter() + seconds
    try:
        while time.perf_counter() < t_end:
            _k32.WaitForSingleObject(ev, 200)
            while True:
                n = cap.GetNextPacketSize()
                if not n:
                    break
                data, n_read, flags, _, _ = cap.GetBuffer()
                if flags & AUDCLNT_BUFFERFLAGS_SILENT:
                    chunks.append(b"\x00" * (n_read * block))
                    silent_frames += n_read
                else:
                    chunks.append(ctypes.string_at(data, n_read * block))
                if flags & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY:
                    discont += 1
                frames += n_read
                cap.ReleaseBuffer(n_read)
    finally:
        client.Stop()
    return b"".join(chunks), {"frames": frames, "silent_frames": silent_frames,
                              "discontinuities": discont,
                              "seconds_captured": round(frames / fmt.nSamplesPerSec, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--exclude", action="store_true", help="capture everything BUT this process tree")
    args = ap.parse_args()

    print(f"probing formats for pid {args.pid}")
    name, fmt = probe_formats(args.pid, not args.exclude)
    if fmt is None:
        raise SystemExit("no format accepted")
    print(f"capturing {args.seconds} s as {name}")
    raw, stats = capture(args.pid, args.seconds, fmt, not args.exclude)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    if args.out:
        with wave.open(args.out, "wb") as w:
            w.setnchannels(fmt.nChannels)
            w.setsampwidth(fmt.wBitsPerSample // 8)
            w.setframerate(fmt.nSamplesPerSec)
            w.writeframes(raw)
        print(f"  wrote {args.out}")


if __name__ == "__main__":
    main()


# --- мікрофон: той самий цикл читання, інший спосіб дістати IAudioClient ----
CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
eRender, eCapture = 0, 1
eConsole = 0
CLSCTX_ALL = 23


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate",
                  (["in"], POINTER(GUID), "iid"), (["in"], DWORD, "dwClsCtx"),
                  (["in"], c_void_p, "pActivationParams"), (["out"], POINTER(c_void_p), "ppInterface")),
        COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], DWORD, "stgmAccess"),
                  (["out"], POINTER(c_void_p), "ppProperties")),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_wchar_p), "ppstrId")),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(DWORD), "pdwState")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], ctypes.c_int, "dataFlow"),
                  (["in"], DWORD, "dwStateMask"), (["out"], POINTER(c_void_p), "ppDevices")),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], ctypes.c_int, "dataFlow"),
                  (["in"], ctypes.c_int, "role"), (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
        COMMETHOD([], HRESULT, "GetDevice", (["in"], c_wchar_p, "pwstrId"),
                  (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
        COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback", (["in"], c_void_p, "pClient")),
        COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback", (["in"], c_void_p, "pClient")),
    ]


def open_mic_stream(fmt, buffer_ms=200):
    """IAudioClient typovoho mikrofona. AUTOCONVERTPCM - shchob prystrij sam
    davav 16 kHz mono, a ne jogo vlasnyj mix format."""
    enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
    dev = enum.GetDefaultAudioEndpoint(eCapture, eConsole)
    raw = dev.Activate(byref(IAudioClient._iid_), CLSCTX_ALL, None)
    client = ctypes.cast(raw, POINTER(IAudioClient))
    flags = (AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
             | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY)
    client.Initialize(AUDCLNT_SHAREMODE_SHARED, flags, buffer_ms * 10000, 0, byref(fmt), None)
    ev = _k32.CreateEventW(None, False, False, None)
    client.SetEventHandle(ev)
    cap = ctypes.cast(client.GetService(byref(IAudioCaptureClient._iid_)), POINTER(IAudioCaptureClient))
    return client, cap, ev, dev.GetId()
