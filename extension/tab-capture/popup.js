// Вікно значка: запис або запис з текстом для цієї вкладки, мікрофон на льоту.
// "Запис" не вантажить модель узагалі - карта на парі вільна; текст тоді
// потім, офлайн. Стан живе в chrome.storage.session - його веде background.js.

const rec = document.getElementById("rec");
const txt = document.getElementById("txt");
const stop = document.getElementById("stop");
const mic = document.getElementById("mic");
const status = document.getElementById("status");

async function render() {
  const s = await chrome.storage.session.get(["active", "phase", "mic", "note"]);
  rec.hidden = txt.hidden = !!s.active;
  stop.hidden = !s.active;
  mic.checked = !!s.mic;
  status.textContent = s.note || "";
}

async function toggle(transcribe) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await chrome.runtime.sendMessage({ target: "background", type: "toggle", tabId: tab.id, transcribe });
}
rec.onclick = () => toggle(false);
txt.onclick = () => toggle(true);
stop.onclick = () => toggle(null);

mic.onchange = () =>
  chrome.runtime.sendMessage({ target: "background", type: "mic", on: mic.checked });

chrome.storage.onChanged.addListener(render);
render();
