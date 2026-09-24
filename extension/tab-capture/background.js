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

async function setActive(tabId) {
  await chrome.storage.session.set({ active: tabId });
  await chrome.action.setBadgeText({ text: tabId ? "REC" : "" });
  await chrome.action.setTitle({
    title: tabId ? "Зупинити захоплення" : "Почати захоплення вкладки",
  });
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
  await chrome.runtime.sendMessage({ target: "offscreen", type: "start", streamId });
  await setActive(tab.id);
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "background") return;
  if (msg.type === "saved") {
    // Місцевий час, а не UTC з toISOString - щоб збігалося з іменами служби.
    const d = new Date(), p = (n) => String(n).padStart(2, "0");
    const stamp = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_` +
                  `${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}`;
    chrome.downloads.download({ url: msg.url, filename: `local-cluster/tab-${stamp}.wav` });
    console.log("saved", msg.stats);
    setActive(null);
  }
});
