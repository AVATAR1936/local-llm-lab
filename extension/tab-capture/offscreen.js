// Прихована сторінка: відкриває потік вкладки і розводить його на дві гілки.
//   1) відтворення рідною частотою - у навушники. Без цього вкладку не
//      чутно: під час захоплення Chrome глушить її звук для користувача;
//   2) запис на 16 кГц - для розпізнавання. Частоту знижує сам AudioContext.

let stream = null, playCtx = null, recCtx = null;
let chunks = [], samples = 0, t0 = 0;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "offscreen") return;
  if (msg.type === "start") start(msg.streamId);
  if (msg.type === "stop") stop();
});

async function start(streamId) {
  stream = await navigator.mediaDevices.getUserMedia({
    audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
    video: false,
  });
  playCtx = new AudioContext();
  playCtx.createMediaStreamSource(stream).connect(playCtx.destination);

  recCtx = new AudioContext({ sampleRate: 16000 });
  await recCtx.audioWorklet.addModule("worklet.js");
  const tap = new AudioWorkletNode(recCtx, "pcm-tap");
  tap.port.onmessage = (e) => { chunks.push(e.data); samples += e.data.length; };
  // Вузол, не під'єднаний до виходу, Chrome може не обробляти - тому
  // під'єднуємо через нульове підсилення: чути нічого не буде.
  const mute = recCtx.createGain();
  mute.gain.value = 0;
  recCtx.createMediaStreamSource(stream).connect(tap).connect(mute).connect(recCtx.destination);

  // Вкладку закрили - потік скінчився: зберігаємо те, що є.
  stream.getAudioTracks()[0].onended = stop;
  chunks = []; samples = 0; t0 = performance.now();
  console.log("start", { play_rate: playCtx.sampleRate, rec_rate: recCtx.sampleRate });
}

function stop() {
  if (!stream) return;
  const wall = (performance.now() - t0) / 1000;
  stream.getTracks().forEach((t) => t.stop());
  playCtx.close(); recCtx.close();
  const stats = {
    play_rate: playCtx.sampleRate, rec_rate: recCtx.sampleRate,
    wall_s: +wall.toFixed(2), audio_s: +(samples / recCtx.sampleRate).toFixed(2),
  };
  const url = URL.createObjectURL(toWav(chunks, samples, recCtx.sampleRate));
  stream = null; chunks = [];
  chrome.runtime.sendMessage({ target: "background", type: "saved", url, stats });
}

function toWav(parts, n, rate) {
  const buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); str(8, "WAVE");
  str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, n * 2, true);
  let o = 44;
  for (const p of parts) for (let i = 0; i < p.length; i++, o += 2) {
    v.setInt16(o, Math.max(-1, Math.min(1, p[i])) * 32767, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}
