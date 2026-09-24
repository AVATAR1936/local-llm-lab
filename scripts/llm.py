# -*- coding: utf-8 -*-
"""Vyklyk gemma4 cherez Ollama: odne vikno dlya vsikh i holosne perepovnennya.

Vikno 65 536, a ne 32 768: para 94 khv (2026-02-10) - 32 308 tokeniv, i z
instrukciyeyu vona zajmala majzhe vse vikno; protokol movchky obryvavsya
pislya ~200 tokeniv vidpovidi, bez pomylky. Zamir 65 536: 100 % GPU, pik
11 258 MB, 46 t/s - yak i na 32 768.

Vikno odne dlya vsikh vyklykiv: pry zmini num_ctx Ollama perezavantazhuye
model'.

Perepovnennya - pomylka, a ne tykhyj obryv (toj samyj pryncyp, shcho
"Prefer No Sysmem Fallback"): do vyklyku - ocinka za znakamy, pislya -
tochno za prompt_eval_count.
"""
import json, urllib.request

MODEL = "gemma4:12b"
NUM_CTX = 65536
# Знаків на токен у gemma на українській стенограмі: 71 209 / 32 570 = 2.19.
# Для оцінки беремо менше - щоб помилятися в бік "не влізе".
CHARS_PER_TOKEN = 2.0
MAX_CHARS_PER_TOKEN = 4.0   # більше - промпт обрізано
BASE = {"temperature": 0.2, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.0}


class ContextOverflow(RuntimeError):
    pass


def ask(prompt, seed=42, predict=3000, fmt=None, **options):
    """Vidpovid' Ollama (dict). Pidnimaye ContextOverflow, yakshcho zapyt z
    zapasom na vidpovid' ne vlazyt' u vikno - do vyklyku chy pislya."""
    est = len(prompt) / CHARS_PER_TOKEN
    if est + predict > NUM_CTX:
        raise ContextOverflow(f"~{est:.0f} prompt tokens + {predict} answer > window {NUM_CTX}")
    body = {"model": MODEL, "prompt": prompt, "stream": False, "think": False,
            "options": {**BASE, **options, "num_ctx": NUM_CTX, "seed": seed, "num_predict": predict}}
    if fmt is not None:
        body["format"] = fmt
    req = urllib.request.Request("http://localhost:11434/api/generate",
                                 data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    r = json.load(urllib.request.urlopen(req, timeout=1800))
    # Ollama мовчки обрізає промпт, що не влазить, - і не до розміру вікна, а
    # приблизно до половини: 8 000 знаків у вікні 2 048 дали 1 027 токенів. За
    # "лічильник уперся у вікно" цього не видно; видно за тим, що знаків на
    # токен стало неправдоподібно багато (справжні тексти - 2.2-2.5, обрізаний
    # - 7.8). prompt_eval_count рахує весь промпт і при повторному кеші.
    n = r.get("prompt_eval_count", 0)
    if n and len(prompt) / n > MAX_CHARS_PER_TOKEN:
        raise ContextOverflow(f"prompt truncated by Ollama: {len(prompt)} chars -> {n} tokens")
    if n + r.get("eval_count", 0) >= NUM_CTX - 1:
        raise ContextOverflow(f"window full: prompt {n} + answer {r.get('eval_count')} >= {NUM_CTX}")
    return r
