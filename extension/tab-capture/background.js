// Service worker: клік по значку -> ідентифікатор потоку вкладки.
// Сам потік тут відкрити не можна (у service worker немає медіа), тому
// ідентифікатор передається у приховану сторінку offscreen.html.

async function ensureOffscreen() {
  const have = await chrome.runtime.getContexts({ contextTypes: ["OFFSCREEN_DOCUMENT"] });
  if (have.length) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["USER_MEDIA"],
    justification: "Захоплення звуку вкладки для локального розпізнавання",
  });
}

// Значок показує стан: "..." - служба вантажить модель, REC - звук іде,
// ERR - сеанс обірвався не з волі користувача (причина - у підказці).
async function show(badge, title, color = "#b00") {
  await chrome.action.setBadgeText({ text: badge });
  await chrome.action.setBadgeBackgroundColor({ color });
  await chrome.action.setTitle({ title });
}

chrome.action.onClicked.addListener(async (tab) => {
  const { active } = await chrome.storage.session.get("active");
  if (active) {
    await chrome.runtime.sendMessage({ target: "offscreen", type: "stop" });
    return;
  }
  await ensureOffscreen();
  // Chrome видає потік вкладки лише у відповідь на дію користувача -
  // тому один клік на кожну пару, автоматично не вийде.
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
  await chrome.storage.session.set({ active: tab.id });
  await show("...", "Служба готується", "#888");
  await chrome.runtime.sendMessage({ target: "offscreen", type: "start", streamId });
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "background") return;
  if (msg.type === "ready") show("REC", `Сеанс ${msg.id}. Клік - зупинити`);
  if (msg.type === "stopped") {
    chrome.storage.session.remove("active");
    if (msg.reason === "user" || msg.reason === "tab closed") show("", "Почати захоплення вкладки");
    else show("ERR", `Зупинено: ${msg.reason}. Клік - почати знову`);
  }
});
