#!/usr/bin/env python3
"""
IPTV avto-yeniləyici.

1. base.m3u  (sənin əl ilə yazdığın siyahı) oxunur. Eyni adlı kanalı bir neçə dəfə
   yazsan, hamısı ehtiyat link sayılır.
2. sources.txt-dəki açıq siyahılardan eyni adlı kanalların əlavə linkləri tapılır.
3. Bütün linklər yoxlanır (playlist + ilk seqment).
4. Nəticə:
   0130.m3u       - hər kanal üçün işləyən ən yaxşı link (birbaşa)
   0130-live.m3u  - Cloudflare Worker linkləri (WORKER_URL verilibsə)
   channels.json  - Worker üçün sıralanmış link siyahısı
   report.md      - hansı kanal ölüdür, hansı dəyişdi
"""
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import requests

BASE_FILE = "base.m3u"
SOURCES_FILE = "sources.txt"
ALIASES_FILE = "aliases.json"
OUT_M3U = "0130.m3u"
OUT_LIVE = "0130-live.m3u"
OUT_JSON = "channels.json"
STATE_FILE = "state.json"
REPORT_FILE = "report.md"

WORKER_URL = os.environ.get("WORKER_URL", "").rstrip("/")
TIMEOUT = 8
MAX_CANDIDATES = 8
THREADS = 32
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

EXT_RE = re.compile(r"^#EXTINF:(-?\d+)\s*(.*?),(.*)$")
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def parse(text):
    items, cur = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            m = EXT_RE.match(line)
            cur = {"attrs": dict(ATTR_RE.findall(m.group(2))), "name": m.group(3).strip()} if m else None
        elif line.startswith("#"):
            continue
        elif cur and line.lower().startswith("http"):
            cur["url"] = line
            items.append(cur)
            cur = None
    return items


def norm(name):
    n = name.lower()
    n = re.sub(r"\[.*?\]|\(.*?\)", " ", n)
    n = re.sub(r"\b(hd|fhd|uhd|sd|4k|1080p|720p|480p|360p)\b", " ", n)
    return re.sub(r"[\W_]+", "", n)


def chan_id(key):
    ascii_part = re.sub(r"[^a-z0-9]", "", key)[:20]
    return f"{ascii_part}-{hashlib.md5(key.encode()).hexdigest()[:6]}"


def check(url, depth=0):
    """Link həqiqətən video verirmi?"""
    if depth > 2 or not url.lower().startswith("http"):
        return False
    try:
        if ".mpd" in url.split("?")[0].lower():
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            return r.ok and "<MPD" in r.text[:3000]

        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
        if not r.ok:
            r.close()
            return False
        data = b""
        for chunk in r.iter_content(8192):
            data += chunk
            if len(data) > 200_000:
                break
        final_url = r.url
        r.close()
        body = data.decode("utf-8", "ignore")
        if "#EXTM3U" not in body:
            return False
        lines = [l.strip() for l in body.splitlines() if l.strip() and not l.startswith("#")]
        if not lines:
            return False
        if "#EXT-X-STREAM-INF" in body:
            return check(urljoin(final_url, lines[0]), depth + 1)
        seg = urljoin(final_url, lines[-1])
        s = requests.get(seg, headers={**HEADERS, "Range": "bytes=0-2047"}, timeout=TIMEOUT, stream=True)
        ok = s.status_code in (200, 206)
        s.close()
        return ok
    except Exception:
        return False


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    if not os.path.exists(BASE_FILE):
        sys.exit(f"{BASE_FILE} tapılmadı. Hazırkı 0130.m3u faylının surətini {BASE_FILE} adı ilə qoy.")

    aliases = {norm(k): norm(v) for k, v in load_json(ALIASES_FILE, {}).items()}
    state = load_json(STATE_FILE, {"choice": {}})

    # 1. əsas siyahı
    channels, order = {}, []
    with open(BASE_FILE, encoding="utf-8") as f:
        for it in parse(f.read()):
            key = norm(it["name"])
            if not key:
                continue
            if key not in channels:
                channels[key] = {"id": chan_id(key), "name": it["name"], "attrs": it["attrs"], "cands": []}
                order.append(key)
            if it["url"] not in [c["url"] for c in channels[key]["cands"]]:
                channels[key]["cands"].append({"url": it["url"], "src": "base"})

    # 2. başqa siyahılardan ehtiyat link axtarışı
    sources = []
    if os.path.exists(SOURCES_FILE):
        with open(SOURCES_FILE, encoding="utf-8") as f:
            sources = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    found = 0
    for src in sources:
        try:
            r = requests.get(src, headers=HEADERS, timeout=40)
            r.raise_for_status()
        except Exception as e:
            print(f"[!] mənbə açılmadı: {src} ({e})")
            continue
        for it in parse(r.text):
            key = norm(it["name"])
            key = aliases.get(key, key)
            ch = channels.get(key)
            if not ch or len(ch["cands"]) >= MAX_CANDIDATES:
                continue
            if it["url"] not in [c["url"] for c in ch["cands"]]:
                ch["cands"].append({"url": it["url"], "src": src})
                found += 1
    print(f"Başqa siyahılardan {found} yeni ehtiyat link tapıldı")

    # 3. yoxlama
    all_urls = sorted({c["url"] for ch in channels.values() for c in ch["cands"]})
    print(f"{len(all_urls)} link yoxlanır...")
    with ThreadPoolExecutor(THREADS) as ex:
        status = dict(zip(all_urls, ex.map(check, all_urls)))

    # 4. seçim
    # Qayda: öz (base) linklərin heç vaxt yalnız GitHub-ın "ölü" hökmü ilə dəyişdirilmir,
    # çünki GitHub xaricdədir və coğrafi bloklanan linkləri görə bilmir.
    # Birbaşa playlist (0130.m3u): işləyən base link, yoxsa birinci base link.
    # Alternativlər yalnız channels.json-da ehtiyat kimi qalır (Worker onları istifadə edir).
    changed, unseen, dead, new_choice = [], [], [], {}
    out_json = {}
    lines = ["#EXTM3U"]
    live_lines = ["#EXTM3U"]
    for key in order:
        ch = channels[key]
        base_urls = [c["url"] for c in ch["cands"] if c["src"] == "base"]
        alt_urls = [c["url"] for c in ch["cands"] if c["src"] != "base"]
        base_ok = [u for u in base_urls if status.get(u)]
        base_bad = [u for u in base_urls if not status.get(u)]
        alt_ok = [u for u in alt_urls if status.get(u)]
        alt_bad = [u for u in alt_urls if not status.get(u)]
        prev = state["choice"].get(ch["id"])
        if prev in base_ok:                  # işləyirsə, yerində saxla (yelləncək olmasın)
            base_ok.remove(prev)
            base_ok.insert(0, prev)
        best = base_ok[0] if base_ok else base_urls[0]
        if base_ok:
            new_choice[ch["id"]] = best
            if prev and prev != best:
                changed.append(f"{ch['name']}: ehtiyat base linkə keçdi")
        elif alt_ok:
            unseen.append(f"{ch['name']} (GitHub-dan görünmür, işləyən alternativ var)")
        else:
            dead.append(ch["name"])
        # Worker sırası: işləyən base, yoxlanmayan base, işləyən alternativ, qalanlar
        out_json[ch["id"]] = {
            "name": ch["name"],
            "urls": base_ok + base_bad + alt_ok + alt_bad,
            "alive": len(base_ok) + len(alt_ok),
        }

        attrs = " ".join(f'{k}="{v}"' for k, v in ch["attrs"].items())
        head = f"#EXTINF:-1 {attrs},{ch['name']}" if attrs else f"#EXTINF:-1,{ch['name']}"
        lines += [head, best]
        if WORKER_URL:
            live_lines += [head, f"{WORKER_URL}/ch/{ch['id']}"]

    state["choice"] = new_choice
    with open(OUT_M3U, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if WORKER_URL:
        with open(OUT_LIVE, "w", encoding="utf-8") as f:
            f.write("\n".join(live_lines) + "\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, separators=(",", ":"))
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)

    alive_total = len(order) - len(dead) - len(unseen)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(f"# Hesabat\n\nGitHub-dan təsdiqlənən kanal: {alive_total} / {len(order)}\n\n")
        f.write("NOT: GitHub serverləri xaricdədir. Aşağıdakı siyahılar yalnız GitHub-ın gördüyüdür, "
                "Azərbaycandan baxanda bu kanalların çoxu işləyə bilər. Əsas linklər silinmir.\n\n")
        f.write("## GitHub-dan görünməyən kanallar (heç bir link açılmır, əsas link saxlanıldı)\n"
                + ("\n".join(f"- {n}" for n in dead) or "- yoxdur") + "\n\n")
        f.write("## Əsas link görünmür, amma alternativ açılır (əsas link saxlanıldı)\n"
                + ("\n".join(f"- {n}" for n in unseen) or "- yoxdur") + "\n\n")
        f.write("## Bu dəfə dəyişənlər\n" + ("\n".join(f"- {n}" for n in changed) or "- yoxdur") + "\n")
    print(f"Hazırdır: {alive_total}/{len(order)} təsdiqləndi, {len(unseen)} alternativli, "
          f"{len(dead)} görünmür, {len(changed)} dəyişdi")


if __name__ == "__main__":
    main()
