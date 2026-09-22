# -*- coding: utf-8 -*-
"""Pidkazaty Windows, de lezhat CUDA-bibilioteky z pip-paketiv nvidia-*.

CTranslate2 i onnxruntime-gpu shukayut cuBLAS, cuDNN ta reshtu sered
katalohiv DLL procesu. Pip kalde ci fajly v site-packages/nvidia/*/bin,
ale Windows tam ne dyvytsya. Oficijna instrukciya faster-whisper radyt
zavantazhyty arhiv rukamy i propysaty PATH; zamist cioho dodayemo
katalohy yavno pered importom.

Vyklykaty TREBA do pershoho importu ctranslate2 abo onnxruntime.
"""
import os
import pathlib
import platform
import site


def add_nvidia_dlls(verbose=False):
    if platform.system() != "Windows":
        return []
    roots = list(site.getsitepackages())
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    added = []
    for p in roots:
        nv = pathlib.Path(p) / "nvidia"
        if not nv.is_dir():
            continue
        for sub in sorted(nv.iterdir()):
            b = sub / "bin"
            if b.is_dir():
                try:
                    os.add_dll_directory(str(b))
                    added.append(str(b))
                except Exception as e:
                    if verbose:
                        print(f"  ! add_dll_directory failed for {b}: {e}")
    return added
