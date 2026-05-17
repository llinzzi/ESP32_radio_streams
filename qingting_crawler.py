#!/usr/bin/env python3
"""
Qingting FM Radio Crawler — updated
Uses browser to navigate provinces, extract channel IDs + names, then probe streams.
"""
import json, re, os, subprocess, concurrent.futures, sys, time
from collections import Counter
from datetime import datetime

OUTPUT_DIR = os.path.expanduser("~/Dev/radio_streams")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "qingting_stations.md")
CACHE_FILE = os.path.join(OUTPUT_DIR, ".qingting_channels.json")
ICY_CACHE = os.path.join(OUTPUT_DIR, ".qingting_icy.json")

# Provinces on the radio page (from browser snapshot)
PROVINCES = [
    "北京", "天津", "河北", "上海", "山西", "内蒙古", "辽宁", "吉林",
    "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "陕西", "甘肃", "宁夏", "新疆", "西藏", "青海",
]

# We'll collect channels via browser, but use terminal+curl for probing.
# The probing will happen in a separate step.

# ============================================================
# 1. Collect channels from browser (will be populated externally)
# ============================================================
# This script is meant to be run AFTER collecting channel data via the browser.
# See qingting_collect.py for the browser-based collection step.
# For now, load from cache or provide empty.

all_channels = []
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f:
        all_channels = json.load(f)
    print(f"Loaded {len(all_channels)} channels from cache")
else:
    print("No channel cache found. Run qingting_collect.py first via browser.")
    print("Fallback: use a range of known IDs")
    # Fallback: known ID ranges from observation
    known_ids = {
        4518: "浙江之声", 4522: "FM93浙江交通之声", 1133: "杭州交通91.8电台",
        4521: "浙江FM99.6", 1163: "西湖之声", 1135: "嘉兴交通广播",
        4519: "浙江经济广播", 4866: "浙江音乐调频", 2812: "FM103.5湖州经济广播",
        15318146: "杭州FM90.7", 1154: "嘉兴综合广播", 1140: "宁波交通广播",
        20639: "新疆电台维语交通文艺广播", 1254: "广东新闻广播",
        1667: "济南新闻广播", 3995: "都市101经济广播",
    }
    all_channels = [{"id": k, "name": v} for k, v in known_ids.items()]
    print(f"Using {len(all_channels)} known IDs as fallback")

# ============================================================
# 2. Probe streams
# ============================================================
print(f"\nProbing {len(all_channels)} channels...")

icy_cache = {}
if os.path.exists(ICY_CACHE):
    with open(ICY_CACHE) as f:
        icy_cache = json.load(f)

to_probe = [ch for ch in all_channels if str(ch["id"]) not in icy_cache]

if to_probe:
    def probe(id_val, name):
        cid = str(id_val)
        info = {"icy_name": "", "icy_br": "", "song_title": "", "format": "", "alive": False}
        url = f"http://lhttp.qingting.fm/live/{cid}/64k.mp3"
        try:
            r = subprocess.run(
                ["curl", "-s", "--max-time", "6", "--connect-timeout", "4",
                 "-H", "Icy-MetaData:1", "-A", "WinampMPEG/5.66",
                 "--dump-header", f"/tmp/qt_{cid}.h",
                 "-o", f"/tmp/qt_{cid}.d",
                 url],
                capture_output=True, timeout=10)
            
            # Check headers
            if os.path.exists(f"/tmp/qt_{cid}.h"):
                with open(f"/tmp/qt_{cid}.h") as fh:
                    for ln in fh:
                        l = ln.lower()
                        if "icy-name:" in l: info["icy_name"] = ln.split(":", 1)[1].strip()
                        elif "icy-br:" in l: info["icy_br"] = ln.split(":", 1)[1].strip()
                try: os.remove(f"/tmp/qt_{cid}.h")
                except: pass
            
            # Check data
            if os.path.exists(f"/tmp/qt_{cid}.d") and os.path.getsize(f"/tmp/qt_{cid}.d") > 0:
                info["alive"] = True
                d = open(f"/tmp/qt_{cid}.d", "rb").read(4)
                if d[:3] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xfa'): info["format"] = "MP3"
                elif d[:4] == b'fLaC': info["format"] = "FLAC"
                elif d[:4] == b'OggS': info["format"] = "OGG"
                else: info["format"] = "Stream"
                sr = subprocess.run(["strings", f"/tmp/qt_{cid}.d"], capture_output=True, text=True, timeout=3)
                m = re.search(r"StreamTitle='([^']+)'", sr.stdout)
                if m: info["song_title"] = m.group(1)
                try: os.remove(f"/tmp/qt_{cid}.d")
                except: pass
            return cid, info
        except:
            for p in [f"/tmp/qt_{cid}.h", f"/tmp/qt_{cid}.d"]:
                if os.path.exists(p): os.remove(p)
            return cid, info

    done = 0
    for bs in range(0, len(to_probe), 30):
        batch = to_probe[bs:bs+30]
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            fs = {ex.submit(probe, e["id"], e["name"]): e for e in batch}
            for f in concurrent.futures.as_completed(fs):
                cid, info = f.result()
                icy_cache[cid] = info
                done += 1
        sys.stdout.write(f"\r  Probed: {done}/{len(to_probe)} ({done*100//len(to_probe)}%)  ")
        sys.stdout.flush()
        time.sleep(0.3)

    with open(ICY_CACHE, "w", encoding="utf-8") as f:
        json.dump(icy_cache, f, indent=2, ensure_ascii=False)
    print()

# ============================================================
# 3. Output
# ============================================================
alive = sum(1 for v in icy_cache.values() if v.get("alive"))
has_name = sum(1 for v in icy_cache.values() if v.get("icy_name"))
has_song = sum(1 for v in icy_cache.values() if v.get("song_title"))
has_br = sum(1 for v in icy_cache.values() if v.get("icy_br"))

lines = [
    "# Qingting FM (蜻蜓FM) Radio Stations",
    "",
    f"Auto-generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    "Source: qtfm.cn (formerly qingting.fm)",
    f"Stream pattern: http://lhttp.qingting.fm/live/{{id}}/64k.mp3",
    "",
    "---",
    "## Summary",
    "",
    "| Metric | Value |",
    "|--------|------:|",
    f"| Total channels | {len(all_channels)} |",
    f"| Alive streams | {alive} |",
    f"| Dead/Timeout | {len(all_channels) - alive} |",
    f"| With ICY name | {has_name} |",
    f"| With bitrate | {has_br} |",
    f"| With song title | {has_song} |",
    "",
    "---",
    "## Station List",
    "",
    "| # | ID | Name | ICY Name | Format | BR | Song Title | Status |",
    "|---|----:|------|----------|--------|----|------------|--------|",
]

idx = 0
for ch in sorted(all_channels, key=lambda x: x["id"]):
    idx += 1
    ci = icy_cache.get(str(ch["id"]), {})
    icon = "\u2705" if ci.get("alive") else "\u274c"
    lines.append(
        f"| {idx:4d} | {ch['id']:>8d} | {ch['name'][:40]:40s} "
        f"| {ci.get('icy_name','')[:30]:30s} | {ci.get('format','?'):8s} "
        f"| {ci.get('icy_br',''):4s} | {ci.get('song_title','')[:40]:40s} | {icon} |"
    )

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print(f"\nDone! Output: {OUTPUT_FILE}")
print(f"  Total: {len(all_channels)}, Alive: {alive}, Song titles: {has_song}")
