// Service worker: команди з вікна значка -> ідентифікатор потоку вкладки.
// Сам потік тут відкрити не можна (у service worker немає медіа), тому
// ідентифікатор передається у приховану сторінку offscreen.html.
//
// Стан у chrome.storage.session: active (id вкладки або нічого), mic,
// note (рядок для вікна). Мікрофон за замовчуванням вимкнений і після
// кожного сеансу вимикається знову.

async function ensureOffscreen() {
  const have = await chrome.runtime.getContexts({ contextTypes: ["OFFSCREEN_DOCUMENT"] });
  if (have.length) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["USER_MEDIA"],
    justification: "Захоплення звуку вкладки для локального розпізнавання",
  });
}

// Значок показує стан: "..." - служба вантажить модель, REC - лише запис,
// TXT - запис з текстом,
// ERR - сеанс обірвався не з волі користувача (причина - у вікні).
async function badge(text, color = "#b00") {
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({ color });
}

async function toggle(tabId, transcribe) {
  const { active, mic } = await chrome.storage.session.get(["active", "mic"]);
  if (active) {
    await chrome.runtime.sendMessage({ target: "offscreen", type: "stop" });
    return;
  }
  await ensureOffscreen();
  // Chrome видає потік вкладки лише у відповідь на дію користувача -
  // тому клік на кожну пару, автоматично не вийде.
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
  await chrome.storage.session.set({ active: tabId, note: "Служба готується" });
  await badge("...", "#888");
  await chrome.runtime.sendMessage({ target: "offscreen", type: "start", streamId, mic: !!mic,
                                     transcribe: !!transcribe });
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "background") return;
  if (msg.type === "toggle") toggle(msg.tabId, msg.transcribe);
  if (msg.type === "mic") {
    chrome.storage.session.set({ mic: msg.on });
    // Сеанс іде - перемикаємо в службі; ні - запам'ятали на старт.
    chrome.runtime.sendMessage({ target: "offscreen", type: "mic", on: msg.on }).catch(() => {});
  }
  if (msg.type === "ready") {
    badge(msg.transcribe ? "TXT" : "REC");
    chrome.storage.session.set({ note: `${msg.transcribe ? "Запис + текст" : "Запис"}: ${msg.id}`, mic: msg.mic });
  }
  if (msg.type === "mic_on") chrome.storage.session.set({ mic: msg.on });
  if (msg.type === "stopped") {
    const ok = msg.reason === "user" || msg.reason === "tab closed";
    badge(ok ? "" : "ERR");
    chrome.storage.session.set({ active: null, mic: false, note: ok ? "" : `Зупинено: ${msg.reason}` });
  }
});
