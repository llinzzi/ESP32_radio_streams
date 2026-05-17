#!/usr/bin/env python3
"""
Radio Station Analyzer
Probes all radio station URLs for codec + ICY metadata (stream name, genre,
bitrate, current song title). Outputs a complete markdown table.
"""
import os, re, json, time, subprocess, concurrent.futures, sys
from collections import Counter
from datetime import datetime

REPO_DIR = os.path.expanduser("~/Dev/radio_streams")
OUTPUT_FILE = os.path.join(REPO_DIR, "station_analysis.md")
PROBE_CACHE = os.path.join(REPO_DIR, ".probe_cache.json")
ICY_CACHE = os.path.join(REPO_DIR, ".icy_cache.json")


# ============================================================
# Helper: classify functions (defined early so usable everywhere)
# ============================================================
def classify_country(name, url):
    n, u = name.lower(), url.lower()
    if re.search(r"[\u4e00-\u9fff]", name) or any(
        kw in n for kw in ["china", "beijing", "shanghai", "cri ", "cnr", "cgtn"]
    ):
        return "China", "Chinese"
    if any(
        d in u for d in [".pl", "polskieradio", "radioagora", "eurozet", "smcdn",
                         "radiostream.pl", "radio90", "radiojura", "radiolodz",
                         "weekendfm", "radiorodzina", "cyberstacja", "bonton",
                         "radiomonster", "radioparty", "nedds24", "widzewfm",
                         "shot2.inten", "inten.pl", "polskiego"]
    ) or any(
        kw in n for kw in ["antyradio", "radio zet", "radio eska", "radio plus",
                           "radio pogoda", "rmf ", "radio 357", "radio nowy swiat",
                           "radio 90", "radio afera", "vox fm", "radio super fm",
                           "radio 7", "oldie fm", "radio jura", "radio lodz",
                           "paloma", "planeta fm", "radio centrum", "meloradio",
                           "chillizet", "radio tok fm", "czworka", "trojk"]
    ):
        return "Poland", "Polish"
    if any(d in u for d in [".fr", "frequence3", "nostalgie", "abf.", "h2o-", "radionti"]):
        return "France", "French"
    if any(d in u for d in [".de", "ffh.de", "radionetz", "radiopaloma", "wunschradio"]):
        return "Germany", "German"
    if any(d in u for d in [".nl", "kink"]) or "kink" in n:
        return "Netherlands", "Dutch"
    if any(d in u for d in [".co.uk", "sharp-stream", "bbc"]):
        return "UK", "English"
    if any(d in u for d in ["181fm", "listen.181fm", "kexp", "streamtheworld"]):
        return "USA", "English"
    if any(d in u for d in [".it", "radiodancefloor"]):
        return "Italy", "Italian"
    if "danubiusradio" in u:
        return "Hungary", "Hungarian"
    if any(d in u for d in [".ro", "rdsnet", "dancefm"]):
        return "Romania", "Romanian"
    if any(d in u for d in [".be", "clubfmserver"]):
        return "Belgium", "Dutch/French"
    if any(d in u for d in [".sk"]) or "funradio" in u:
        return "Slovakia", "Slovak"
    return "International", "English"


def classify_genre(name, url):
    pair = (name + " " + url).lower()
    genres = [
        ("Rock/Metal", ["rock", "metal", "hard ", "punk", "grunge", "alternative",
                        "distortion", "hairband", "death.fm", "kink_distortion"]),
        ("Jazz/Blues", ["jazz", "blues", "bebop", "smoothjazz", "smooth jazz"]),
        ("Classical", ["classical music", "classical"]),
        ("Country", ["country", "highway", "front porch", "realcountry"]),
        ("Dance/Electronic", ["dance", "electronic", "techno", "trance", "edm",
                              "party", "energy", "jammin", "technoclub", "q-dance",
                              "dancefloor", "eurodance", "club", "rave", "electro"]),
        ("Hip-Hop/R&B", ["hip hop", "rnb", "randb", "oldschool hip", "true r&b"]),
        ("Pop", ["pop", "tophits", "top 40", "hot dance"]),
        ("Religious", ["orthodoxia", "gospel", "christian", "praise", "worship"]),
        ("News/Talk", ["news", "talk", "tok fm", "bbc", "public radio", "polskiego radia"]),
        ("Oldies/Retro", ["oldies", "retro", "gold ", "70s", "80s", "90s", "00s",
                          "2000s", "evergreens", "classic hits", "nostalgie", "retrodance"]),
        ("Latin/World", ["latino", "salsa", "reggae", "world", "reggaeton", "brazil", "afro"]),
        ("Soul/Funk", ["soul", "funk", "motown", "disco", "groove", "ballads"]),
        ("Children", ["kids", "children", "family"]),
        ("Lounge/Chill", ["chill", "lounge", "ambient", "relax", "chilled", "breeze",
                          "smooth", "mellow", "chillizet"]),
        ("Varied/General", ["radio", "fm"]),
    ]
    for genre, keywords in genres:
        for kw in keywords:
            if kw in pair:
                return genre
    return "General/Pop"


def classify_format(url, probed):
    if probed and (probed.startswith("dead") or probed == "dead/timeout"):
        return probed
    if probed and probed not in ("unknown", ""):
        return probed
    u = url.lower()
    if u.endswith(".mp3") or ".mp3?" in u: return "MP3"
    if u.endswith(".aac") or ".aac?" in u: return "AAC"
    if u.endswith(".ogg") or ".ogg?" in u: return "OGG"
    if u.endswith(".flac") or ".flac?" in u: return "FLAC"
    if u.endswith(".m3u8"): return "HLS"
    if u.endswith(".m3u"): return "M3U"
    if u.endswith(".pls"): return "PLS"
    return probed if probed else "unknown"


COUNTRY_EMOJI = {
    "Poland": "\U0001f1f5\U0001f1f1 Poland",
    "France": "\U0001f1eb\U0001f1f7 France",
    "Germany": "\U0001f1e9\U0001f1ea Germany",
    "Netherlands": "\U0001f1f3\U0001f1f1 Netherlands",
    "UK": "\U0001f1ec\U0001f1e7 UK",
    "USA": "\U0001f1fa\U0001f1f8 USA",
    "Italy": "\U0001f1ee\U0001f1f9 Italy",
    "Hungary": "\U0001f1ed\U0001f1fa Hungary",
    "Romania": "\U0001f1f7\U0001f1f4 Romania",
    "Belgium": "\U0001f1e7\U0001f1ea Belgium",
    "Slovakia": "\U0001f1f8\U0001f1f0 Slovakia",
    "International": "\U0001f30d International",
}


# ============================================================
# 1. Parse all bank files
# ============================================================
print("Reading bank files...")
all_stations = []
for fname in sorted(os.listdir(REPO_DIR)):
    if not fname.startswith("bank") or not fname.endswith(".txt"):
        continue
    fpath = os.path.join(REPO_DIR, fname)
    bank_num = fname.replace("bank", "").replace(".txt", "").replace("_Christmas", "-Xmas")
    with open(fpath, encoding="ISO-8859-1") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            url_match = re.search(r"(https?://\S+)", line)
            if not url_match:
                continue
            stream_url = url_match.group(1).rstrip("/")
            name_part = line[:url_match.start()].strip()
            name_part = re.sub(r"\s*Bank\s+\d+\s+Stacja\s+\d+\s*$", "", name_part).strip()
            all_stations.append({"bank": bank_num, "name": name_part, "url": stream_url})

print(f"  Total stations: {len(all_stations)}")


# ============================================================
# 2. Probe URLs — codec + ICY metadata
# ============================================================
probe_cache = {}
icy_cache = {}

if os.path.exists(PROBE_CACHE):
    try:
        with open(PROBE_CACHE) as f:
            probe_cache = json.load(f)
    except Exception:
        pass
if os.path.exists(ICY_CACHE):
    try:
        with open(ICY_CACHE) as f:
            icy_cache = json.load(f)
    except Exception:
        pass

# --- Pass 1: Codec ---
to_probe = [s for s in all_stations if s["url"] not in probe_cache]
print(f"  Codec cache: {len(probe_cache)}, to probe: {len(to_probe)}")

if to_probe:
    print("Probing codec...", flush=True)
    def probe_codec(url):
        try:
            r = subprocess.run(
                ["curl", "-s", "--max-time", "6", "--connect-timeout", "4",
                 "-A", "Mozilla/5.0", "--location",
                 "-o", "/dev/null", "--write-out", "%{content_type}:%{http_code}", url],
                capture_output=True, text=True, timeout=8)
            out = r.stdout.strip()
            if not out or out.startswith(":"):
                return url, "dead/timeout"
            ct, _, code = out.partition(":")
            code = code.strip()
            ct = ct.strip().lower()
            if code.startswith("30") and "text/html" in ct:
                return url, "redirect"
            if "audio/mpeg" in ct: return url, "MP3"
            elif "audio/aac" in ct: return url, "AAC"
            elif "audio/ogg" in ct or "application/ogg" in ct: return url, "OGG"
            elif "audio/flac" in ct: return url, "FLAC"
            elif "audio/x-scpls" in ct or "audio/scpls" in ct: return url, "PLS"
            elif "audio/x-mpegurl" in ct: return url, "M3U"
            elif "audio" in ct: return url, ct.replace("audio/", "").split(";")[0].upper()
            elif "text/html" in ct: return url, "dead(html)"
            elif "text/plain" in ct: return url, "dead(text)"
            else: return url, f"other({ct.split(';')[0]})"
        except:
            return url, "dead/timeout"

    for bs in range(0, len(to_probe), 100):
        batch = to_probe[bs:bs+100]
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
            fs = {ex.submit(probe_codec, e["url"]): e for e in batch}
            for f in concurrent.futures.as_completed(fs):
                url, fmt = f.result()
                probe_cache[url] = fmt
        print(f"    codec {min(bs+100, len(to_probe))}/{len(to_probe)}", flush=True)
        time.sleep(0.3)

    with open(PROBE_CACHE, "w") as f:
        json.dump(probe_cache, f, indent=2)
    print("  Codec probe done.")

# --- Pass 2: ICY metadata ---
alive_urls = {u for u, f in probe_cache.items()
              if f not in ("dead/timeout", "dead(html)", "dead(text)", "dead(xml)", "redirect")}
to_icy = [s for s in all_stations if s["url"] in alive_urls and s["url"] not in icy_cache]

if to_icy:
    print(f"Probing ICY metadata for {len(to_icy)} stations...", flush=True)

    def probe_icy(url):
        info = {"icy_name": "", "icy_br": "", "icy_genre": "", "song_title": "",
                "icy_url": "", "icy_desc": "", "icy_pub": "", "icy_metaint": ""}
        hid = abs(hash(url)) % 1000000
        hdr = f"/tmp/ih_{hid}.txt"
        dat = f"/tmp/id_{hid}.bin"
        try:
            subprocess.run(
                ["curl", "-s", "--max-time", "7", "--connect-timeout", "5",
                 "-H", "Icy-MetaData:1", "-A", "WinampMPEG/5.66",
                 "--dump-header", hdr, "-o", dat, url],
                capture_output=True, timeout=10)
            if os.path.exists(hdr):
                with open(hdr) as fh:
                    for ln in fh:
                        l = ln.lower()
                        if "icy-name:" in l: info["icy_name"] = ln.split(":", 1)[1].strip()
                        elif "icy-br:" in l: info["icy_br"] = ln.split(":", 1)[1].strip()
                        elif "icy-genre:" in l: info["icy_genre"] = ln.split(":", 1)[1].strip()
                        elif "icy-url:" in l: info["icy_url"] = ln.split(":", 1)[1].strip()
                        elif "icy-description:" in l: info["icy_desc"] = ln.split(":", 1)[1].strip()
                        elif "icy-pub:" in l: info["icy_pub"] = ln.split(":", 1)[1].strip()
                        elif "icy-metaint:" in l or "icy-index-metadata:" in l:
                            info["icy_metaint"] = ln.split(":", 1)[1].strip()
                try: os.remove(hdr)
                except: pass
            if os.path.exists(dat) and os.path.getsize(dat) > 0:
                sr = subprocess.run(["strings", dat], capture_output=True, text=True, timeout=3)
                m = re.search(r"StreamTitle='([^']+)'", sr.stdout)
                if m: info["song_title"] = m.group(1)
                try: os.remove(dat)
                except: pass
            return url, info
        except:
            for p in [hdr, dat]:
                if os.path.exists(p):
                    try: os.remove(p)
                    except: pass
            return url, info

    done = 0
    for bs in range(0, len(to_icy), 50):
        batch = to_icy[bs:bs+50]
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            fs = {ex.submit(probe_icy, e["url"]): e for e in batch}
            for f in concurrent.futures.as_completed(fs):
                url, ci = f.result()
                icy_cache[url] = ci
                done += 1
        sys.stdout.write(f"\r    ICY: {done}/{len(to_icy)} ({done*100//len(to_icy)}%)  ")
        sys.stdout.flush()
        time.sleep(0.3)

    with open(ICY_CACHE, "w") as f:
        json.dump(icy_cache, f, indent=2)
    print("\n  ICY probe done. Cached: {}".format(len(icy_cache)))


# ============================================================
# 3. Classify all stations
# ============================================================
print("Classifying stations...")
for s in all_stations:
    raw_country, s["language"] = classify_country(s["name"], s["url"])
    s["country_emoji"] = COUNTRY_EMOJI.get(raw_country, raw_country)
    s["genre"] = classify_genre(s["name"], s["url"])
    s["probed"] = probe_cache.get(s["url"], "unknown")
    s["format"] = classify_format(s["url"], s["probed"])
    s["icy"] = icy_cache.get(s["url"], {})


# ============================================================
# 4. Stats
# ============================================================
country_stats = Counter(s["country_emoji"] for s in all_stations)
lang_stats = Counter(s["language"] for s in all_stations)
genre_stats = Counter(s["genre"] for s in all_stations)
format_stats = Counter(s["format"] for s in all_stations)
alive = sum(1 for s in all_stations if s["probed"] not in (
    "dead/timeout", "dead(html)", "dead(text)", "dead(xml)", "redirect"))
dead_count = len(all_stations) - alive

icy_n = sum(1 for s in all_stations if s["icy"].get("icy_name"))
icy_g = sum(1 for s in all_stations if s["icy"].get("icy_genre"))
icy_b = sum(1 for s in all_stations if s["icy"].get("icy_br"))
icy_m = sum(1 for s in all_stations if s["icy"].get("icy_metaint"))
icy_s = sum(1 for s in all_stations if s["icy"].get("song_title"))


# ============================================================
# 5. Output
# ============================================================
print("Writing output...")

lines = [
    "# Radio Stations -- Auto Analysis",
    "",
    f"Auto-generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    "Source: dzikakuna/ESP32_radio_streams",
    "",
    "---",
    "## Summary",
    "",
    "| Metric | Value |",
    "|--------|------:|",
    f"| Total | {len(all_stations)} |",
    f"| Alive | {alive} |",
    f"| Dead/Timeout | {dead_count} |",
    "",
    "### ICY Metadata",
    "",
    "| Metric | Count |",
    "|--------|------:|",
    f"| With stream name | {icy_n} |",
    f"| With genre info | {icy_g} |",
    f"| With bitrate | {icy_b} |",
    f"| With metadata support | {icy_m} |",
    f"| With current song title | {icy_s} |",
    "",
    "### Format Distribution",
    "",
    "| Format | Count |",
    "|--------|------:|",
]
for f, c in sorted(format_stats.items(), key=lambda x: -x[1]):
    lines.append(f"| {f} | {c} |")
lines += ["", "### Country Distribution", "", "| Country | Count |", "|---------|------:|"]
for c, n in sorted(country_stats.items(), key=lambda x: -x[1]):
    lines.append(f"| {c} | {n} |")
lines += ["", "### Genre Distribution", "", "| Genre | Count |", "|------:|------:|"]
for g, n in sorted(genre_stats.items(), key=lambda x: -x[1]):
    lines.append(f"| {g} | {n} |")
lines += ["", "### Language Distribution", "", "| Language | Count |", "|----------|------:|"]
for l, n in sorted(lang_stats.items(), key=lambda x: -x[1]):
    lines.append(f"| {l} | {n} |")
lines += ["", "---", "", "## Full Station List", "",
          "| # | Bank | Station Name | Country | Language | Genre | Format | Status | ICY Name | BR | Song Title | URL |",
          "|---|------:|-------------|---------|----------|-------|--------|--------|----------|----|------------|-----|"]

for idx, s in enumerate(all_stations, 1):
    ic = s["icy"]
    p = s["probed"]
    icon = "\u2705"
    if p == "dead/timeout": icon = "\u23f1\ufe0f"
    elif p.startswith("dead"): icon = "\U0001f480"
    elif p == "redirect": icon = "\u21aa\ufe0f"
    lines.append(
        f"| {idx:4d} | {s['bank']:<10s} | {s['name'].replace('|', '/')} "
        f"| {s['country_emoji']} | {s['language']:8s} | {s['genre']:18s} "
        f"| {s['format']:15s} | {icon} "
        f"| {ic.get('icy_name','')[:30]:30s} | {ic.get('icy_br',''):4s} "
        f"| {ic.get('song_title','')[:40]:40s} | {s['url'].replace('|', '')} |"
    )

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print(f"\nDone! Output: {OUTPUT_FILE}")
print(f"   Total: {len(all_stations)}, Alive: {alive}, Dead: {dead_count}")
print(f"   ICY names: {icy_n}, BR: {icy_b}, Song titles: {icy_s}")
