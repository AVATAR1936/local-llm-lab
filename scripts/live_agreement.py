# -*- coding: utf-8 -*-
"""LocalAgreement: potokove rozpiznavannya Whisper iz pidtverdzhennyam.

Yadro vzyate z ufal/whisper_streaming (whisper_online.py, MIT,
(c) 2023 Dominik Machacek, ÚFAL MFF UK) i skorochene: lyshe HypothesisBuffer
i OnlineASRProcessor, bez librosa/torch. Sam paket i WhisperLiveKit ne
stavymo: toj tyahne CPU-zbirky onnxruntime i torch u nashe seredovyshche.

Mekhanizm: bufer zvuku roste, kozhen cykl rozpiznayetsya CILYM zanovo.
Slova, na yakykh zijshlysya dva ostanni rozpiznavannya, pidtverdzhuyutsya i
bil'she ne zminyuyut'sya; zvuk pid nymy vidrizayet'sya, koly bufer dovshyj
za trim_sec.
"""
import numpy as np

SR = 16000


class HypothesisBuffer:
    def __init__(self):
        self.commited_in_buffer = []
        self.buffer = []
        self.new = []
        self.last_commited_time = 0.0

    def insert(self, new, offset):
        # Лишаємо тільки слова, що починаються після останнього підтвердженого.
        new = [(a + offset, b + offset, t) for a, b, t in new]
        self.new = [(a, b, t) for a, b, t in new if a > self.last_commited_time - 0.1]
        if self.new and abs(self.new[0][0] - self.last_commited_time) < 1 and self.commited_in_buffer:
            # Початок нової гіпотези може повторювати хвіст підтвердженого
            # (1..5 слів) — такий повтор відкидаємо.
            cn, nn = len(self.commited_in_buffer), len(self.new)
            for i in range(1, min(cn, nn, 5) + 1):
                c = " ".join(w[2] for w in self.commited_in_buffer[-i:])
                tail = " ".join(w[2] for w in self.new[:i])
                if c == tail:
                    del self.new[:i]
                    break

    def flush(self):
        # Підтверджене = найдовший спільний префікс двох останніх гіпотез.
        commit = []
        while self.new and self.buffer and self.new[0][2] == self.buffer[0][2]:
            w = self.new.pop(0)
            self.buffer.pop(0)
            commit.append(w)
            self.last_commited_time = w[1]
        self.buffer, self.new = self.new, []
        self.commited_in_buffer.extend(commit)
        return commit

    def pop_commited(self, time):
        while self.commited_in_buffer and self.commited_in_buffer[0][1] <= time:
            self.commited_in_buffer.pop(0)


class OnlineASRProcessor:
    def __init__(self, transcribe, trim_sec=15.0, use_prompt=True):
        """transcribe(audio, prompt) -> (words [(beg, end, text)], segment_ends)."""
        self.transcribe = transcribe
        self.trim_sec = trim_sec
        self.use_prompt = use_prompt
        self.audio = np.zeros(0, dtype=np.float32)
        self.hyp = HypothesisBuffer()
        self.offset = 0.0
        self.commited = []

    def insert_audio_chunk(self, audio):
        self.audio = np.append(self.audio, audio)

    def prompt(self):
        # Підказка — до 200 знаків підтвердженого тексту, що вже вийшов за
        # межі буфера. Той самий механізм, що в записі 3 годував петлю:
        # тому він вимикається перемикачем use_prompt.
        if not self.use_prompt:
            return ""
        k = max(0, len(self.commited) - 1)
        while k > 0 and self.commited[k - 1][1] > self.offset:
            k -= 1
        out, n = [], 0
        for _, _, t in reversed(self.commited[:k]):
            if n >= 200:
                break
            out.append(t)
            n += len(t) + 1
        return "".join(reversed(out))

    def process_iter(self):
        words, seg_ends = self.transcribe(self.audio, self.prompt())
        self.hyp.insert(words, self.offset)
        o = self.hyp.flush()
        self.commited.extend(o)
        if len(self.audio) / SR > self.trim_sec:
            self._trim(seg_ends)
        return o

    def draft(self):
        return self.hyp.buffer

    def _trim(self, seg_ends):
        # Ріжемо буфер по кінцю передостаннього сегмента, що вже весь
        # підтверджений: далі розпізнається лише непідтверджений хвіст.
        if not self.commited or len(seg_ends) < 2:
            return
        t = self.commited[-1][1]
        ends = list(seg_ends)
        e = ends[-2] + self.offset
        while len(ends) > 2 and e > t:
            ends.pop()
            e = ends[-2] + self.offset
        if e <= t:
            self.hyp.pop_commited(e)
            self.audio = self.audio[int((e - self.offset) * SR):]
            self.offset = e

    def finish(self):
        o = self.hyp.buffer
        self.hyp.buffer = []
        self.commited.extend(o)
        return o
