// Cloudflare Worker: oxuyanda işləyən linki seçib yönləndirir.
// Playlist linki: https://SENIN-WORKER.workers.dev/ch/<kanal-id>
// Worker dəyişəni (Settings -> Variables): DATA_URL = https://mmirzaagha.github.io/0130/channels.json

const DATA_TTL = 300_000;   // channels.json 5 dəq keşlənir
const ALIVE_TTL = 60_000;   // yoxlama nəticəsi 1 dəq keşlənir
const CHECK_TIMEOUT = 3000;

let data = null, dataAt = 0;
const alive = new Map();

async function getData(env) {
  if (data && Date.now() - dataAt < DATA_TTL) return data;
  const r = await fetch(env.DATA_URL, { cf: { cacheTtl: 120 } });
  data = await r.json();
  dataAt = Date.now();
  return data;
}

async function isAlive(url) {
  const hit = alive.get(url);
  if (hit && Date.now() - hit.t < ALIVE_TTL) return hit.ok;
  let ok = false;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), CHECK_TIMEOUT);
    const r = await fetch(url, { signal: ctrl.signal, headers: { "User-Agent": "Mozilla/5.0" } });
    clearTimeout(timer);
    if (r.ok) {
      if (url.split("?")[0].includes(".mpd")) {
        ok = true;
      } else {
        const text = await r.text();
        ok = text.includes("#EXTM3U");
      }
    }
  } catch (e) { ok = false; }
  alive.set(url, { ok, t: Date.now() });
  return ok;
}

export default {
  async fetch(request, env) {
    const id = new URL(request.url).pathname.split("/").filter(Boolean).pop();
    let channels;
    try { channels = await getData(env); } catch (e) { return new Response("data yoxdur", { status: 502 }); }
    const ch = channels[id];
    if (!ch) return new Response("kanal tapılmadı", { status: 404 });

    // GitHub yoxlamasının işləyən saydığı linklər əvvəldə gəlir
    for (const url of ch.urls) {
      if (await isAlive(url)) return Response.redirect(url, 302);
    }
    return Response.redirect(ch.urls[0], 302);
  },
};
