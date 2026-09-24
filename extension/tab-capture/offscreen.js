// Прихована сторінка: відкриває потік вкладки і розводить його на дві гілки.
//   1) відтворення рідною частотою - у навушники. Без цього вкладку не
//      чутно: під час захоплення Chrome глушить її звук для користувача;
//   2) 16 кГц моно - у службу по WebSocket. Частоту знижує сам AudioContext.
// Запис на диск веде служба, як і для процесного захоплення.

const SERVICE = "ws://127.0.0.1:8756/api/live/tab";
const BATCH = 1600;              // 100 мс при 16 кГц: 10 повідомлень на секунду

let stream = null, playCtx = null, recCtx = null, sock = null;
let ready = false, batch = new Float32Array(BATCH), fill = 0;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "offscreen") return;
  if (msg.type === "start") start(msg.streamId, msg.mic, msg.transcribe).catch((e) => fail(String(e)));
  if (msg.type === "stop") stop("user");
  if (msg.type === "mic" && ready) sock.send(JSON.stringify({ type: "mic", on: msg.on }));
});

function report(type, extra) {
  chrome.runtime.sendMessage({ target: "background", type, ...extra });
}

function fail(reason) {
  console.error(reason);
  stop(reason);
}

function push(block) {
  if (!ready) return;           // до "ready" служба ще вантажить модель
  let i = 0;
  while (i < block.length) {
    const n = Math.min(block.length - i, BATCH - fill);
    batch.set(block.subarray(i, i + n), fill);
    fill += n; i += n;
    if (fill === BATCH) {
      sock.send(batch.buffer);
      batch = new Float32Array(BATCH); fill = 0;
    }
  }
}

async function start(streamId, mic, transcribe) {
  sock = new WebSocket(`${SERVICE}?mic=${mic ? 1 : 0}&transcribe=${transcribe ? 1 : 0}`);
  sock.binaryType = "arraybuffer";
  sock.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "ready") {
      ready = true;
      report("ready", { id: m.id, mic: m.mic, transcribe: m.transcribe });
    }
    if (m.type === "mic") report("mic_on", { on: m.on });
  };
  sock.onclose = (e) => { if (stream) fail(`service closed: ${e.code} ${e.reason}`); };
  sock.onerror = () => fail("service unreachable: " + SERVICE);

  stream = await navigator.mediaDevices.getUserMedia({
    audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
    video: false,
  });
  playCtx = new AudioContext();
  playCtx.createMediaStreamSource(stream).connect(playCtx.destination);

  recCtx = new AudioContext({ sampleRate: 16000 });
  await recCtx.audioWorklet.addModule("worklet.js");
  const tap = new AudioWorkletNode(recCtx, "pcm-tap");
  tap.port.onmessage = (e) => push(e.data);
  // Вузол, не під'єднаний до виходу, Chrome може не обробляти - тому
  // під'єднуємо через нульове підсилення: чути нічого не буде.
  const mute = recCtx.createGain();
  mute.gain.value = 0;
  recCtx.createMediaStreamSource(stream).connect(tap).connect(mute).connect(recCtx.destination);

  // Вкладку закрили - потік скінчився, сеанс теж.
  stream.getAudioTracks()[0].onended = () => stop("tab closed");
}

function stop(reason) {
  const s = stream;
  stream = null; ready = false; fill = 0;
  if (s) s.getTracks().forEach((t) => t.stop());
  if (playCtx) playCtx.close();
  if (recCtx) recCtx.close();
  playCtx = recCtx = null;
  if (sock && sock.readyState <= 1) sock.close();
  sock = null;
  report("stopped", { reason });
}
