// Вікно значка: почати/зупинити захоплення цієї вкладки і мікрофон на льоту.
// Стан живе в chrome.storage.session - його веде background.js.

const go = document.getElementById("go");
const mic = document.getElementById("mic");
const status = document.getElementById("status");

async function render() {
  const s = await chrome.storage.session.get(["active", "phase", "mic", "note"]);
  go.textContent = s.active ? "Зупинити" : "Почати";
  mic.checked = !!s.mic;
  status.textContent = s.note || "";
}

go.onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await chrome.runtime.sendMessage({ target: "background", type: "toggle", tabId: tab.id });
};

mic.onchange = () =>
  chrome.runtime.sendMessage({ target: "background", type: "mic", on: mic.checked });

chrome.storage.onChanged.addListener(render);
render();
