#!/usr/bin/env python3
"""
Qingting FM — Browser-based channel collection
Navigate to radiopage, click each province, extract all station links.
Run this with the browser tools.
"""
from hermes_tools import browser_navigate, browser_click, browser_console, browser_snapshot
import json, os, time

CACHE_FILE = os.path.expanduser("~/Dev/radio_streams/.qingting_channels.json")

# We'll collect channels using the browser
# Call collect_qingting_channels() from the agent

def collect_qingting_channels():
    """Navigate, collect, and save all Qingting channels."""
    PROVINCES = {
        "北京": "@e133", "天津": "@e134", "河北": "@e135",
        "上海": "@e136", "山西": "@e137", "内蒙古": "@e138",
        "辽宁": "@e139", "吉林": "@e140", "黑龙江": "@e141",
        "江苏": "@e142", "浙江": "@e143", "安徽": "@e144",
        "福建": "@e145", "江西": "@e146", "山东": "@e147",
        "河南": "@e148", "湖北": "@e149", "湖南": "@e150",
        "广东": "@e151", "广西": "@e152", "海南": "@e153",
        "重庆": "@e154", "四川": "@e155", "贵州": "@e156",
        "云南": "@e157", "陕西": "@e158", "甘肃": "@e159",
        "宁夏": "@e160", "新疆": "@e161", "西藏": "@e162",
        "青海": "@e163",
    }
    
    all_channels = {}
    
    # Start at radiopage
    r = browser_navigate("https://www.qtfm.cn/radiopage/")
    time.sleep(2)
    
    for prov_name, prov_ref in PROVINCES.items():
        print(f"Collecting {prov_name}...")
        
        # Click province button to expand dropdown
        browser_click("@e132")  # Click "浙江台" button
        time.sleep(0.5)
        browser_click(prov_ref)
        time.sleep(1.5)
        
        # Extract channels from current page
        for page_num in range(1, 15):  # Max 14 pages per province
            r = browser_console(expression=
                "JSON.stringify(Array.from(document.querySelectorAll('a[href^=\"/radios/\"]')).map(a => ({id: a.href.match(/radios\\/(\\d+)/)[1], name: a.textContent.trim()})).filter(x => x.name))"
            )
            if r.get("result"):
                try:
                    stations = json.loads(r["result"])
                    for s in stations:
                        if s["id"] and s["name"] and s["id"] not in all_channels:
                            all_channels[s["id"]] = s["name"]
                            print(f"  + [{s['id']}] {s['name']}")
                except:
                    pass
            
            # Try next page
            # Check if next page button exists and is enabled
            snap = browser_snapshot()
            if "Next page" in str(snap) and "disabled" not in str(snap):
                # Click page numbers - look for page buttons
                pass  # Will need to implement pagination
        
        print(f"  Found: {len(all_channels)} total so far")
    
    # Also collect from "网络台" tab
    browser_click("@e121")  # Click "网络台"
    time.sleep(2)
    # ... extract
    
    # Also collect from "分类" tab
    # ... similar
    
    # Save
    channels_list = [{"id": int(k), "name": v} for k, v in all_channels.items()]
    channels_list.sort(key=lambda x: x["id"])
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(channels_list, f, ensure_ascii=False, indent=2)
    
    print(f"\nSaved {len(channels_list)} channels to {CACHE_FILE}")
    return channels_list
