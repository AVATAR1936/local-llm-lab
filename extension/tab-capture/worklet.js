// Працює в аудіопотоці браузера: зводить у моно і віддає сирі семпли
// блоками по 128 (стільки Web Audio обробляє за один виклик).
class PcmTap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0];
    if (ch.length) {
      const l = ch[0], r = ch[1] || ch[0];
      const out = new Float32Array(l.length);
      for (let i = 0; i < l.length; i++) out[i] = (l[i] + r[i]) / 2;
      this.port.postMessage(out, [out.buffer]);
    }
    return true;
  }
}
registerProcessor("pcm-tap", PcmTap);
