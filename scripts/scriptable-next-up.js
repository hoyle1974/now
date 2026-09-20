// Scriptable (iOS) widget: shows the "Next up" list, incl. on the Lock Screen.
// Setup: paste into a new Scriptable script, fill in TOKEN, then add a Scriptable
// widget (Lock Screen: rectangular; Home Screen: small/medium) and pick this script.
// TOKEN is the WIDGET_TOKEN env var on the Cloud Run service; it only unlocks GET /todos/next.
// BASE: your service URL (`gcloud run services describe <service> --format="value(status.url)"`).
const BASE = "https://YOUR-SERVICE-URL";
const TOKEN = "PASTE_WIDGET_TOKEN_HERE";

const lock = config.widgetFamily === "accessoryRectangular";
const limit = lock ? 3 : config.widgetFamily === "small" ? 4 : 6;

async function load() {
  const req = new Request(`${BASE}/todos/next?limit=${limit}`);
  req.headers = { "X-Widget-Token": TOKEN };
  return (await req.loadJSON()).items;
}

const w = new ListWidget();
w.url = BASE;
w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);
try {
  const items = await load();
  if (!lock) {
    const h = w.addText("Next up");
    h.font = Font.boldSystemFont(13);
    w.addSpacer(4);
  }
  if (!items.length) w.addText("Nothing to do");
  for (const it of items) {
    const t = w.addText(`${lock ? "" : it.rank + ". "}${it.title}`);
    t.font = lock ? Font.systemFont(12) : Font.systemFont(13);
    t.lineLimit = 1;
    if (it.blocked_by.length) t.textOpacity = 0.6;
  }
} catch (e) {
  w.addText("Next up: can't load");
}
if (config.runsInWidget) Script.setWidget(w); else await w.presentMedium();
Script.complete();
