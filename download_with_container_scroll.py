#!/usr/bin/env python3
"""
Download alltuu album with correct container scrolling.
Target: https://m.alltuu.com/album/ATTTTYHS9L000UAB/4521762277?menu=live
"""

import os, re, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ALBUM_URL = "https://m.alltuu.com/album/ATTTTYHS9L000UAB/4521762277?menu=live"
OUTPUT_DIR = r"D:\第23届广东省少年儿童发明奖（深圳）"
HEADLESS = True
MAX_RETRIES = 3

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "", name).strip() or "unnamed"

Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=HEADLESS)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
                   "Mobile/15E148 Safari/604.1",
        viewport={"width": 390, "height": 844},
        device_scale_factor=3,
    )
    page = context.new_page()

    fplN_urls = []
    def handle_route(route, request):
        url = request.url
        if "/rest/v4c/fplN/" in url and url not in fplN_urls:
            fplN_urls.append(url)
            print(f"[API] Captured fplN #{len(fplN_urls)}")
        route.continue_()

    page.route("**/*", handle_route)
    print(f"[1/3] Navigating to album page...")
    page.goto(ALBUM_URL, wait_until="networkidle", timeout=30000)
    print("  DOM ready, scrolling inside container...")

    # Scroll inside the container element, not window
    prev_count = 0
    stall_count = 0
    for i in range(200):
        time.sleep(1.5)
        page.evaluate("""
            () => {
                const el = document.querySelector('.component-scroll') || document.querySelector('.album-scrollList');
                if (el) el.scrollTop = el.scrollHeight;
            }
        """)
        if len(fplN_urls) > prev_count:
            prev_count = len(fplN_urls)
            stall_count = 0
            print(f"  scroll {i+1}: NEW fplN! total={len(fplN_urls)}")
        else:
            stall_count += 1
            if i % 10 == 0:
                print(f"  scroll {i+1}: fplN={len(fplN_urls)} (stall={stall_count})")
        if stall_count >= 30 and len(fplN_urls) > 0:
            print(f"  Stopped: no new pages after {stall_count} scrolls")
            break

    time.sleep(2)
    page.unroute("**/*")

    print(f"\n[2/3] Captured {len(fplN_urls)} API request(s)")
    if not fplN_urls:
        print("[ERROR] No photo list API captured")
        browser.close()
        exit(1)

    all_photos = []
    for api_idx, api_url in enumerate(fplN_urls, 1):
        print(f"  Fetching page {api_idx}/{len(fplN_urls)}...")
        result = page.evaluate("""
            async (url) => {
                const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
                if (!resp.ok) return {error: resp.status, text: await resp.text()};
                return await resp.json();
            }
        """, api_url)
        
        if 'd' in result:
            photos = result['d']
            all_photos.extend(photos)
            print(f"    -> {len(photos)} photos")
        else:
            print(f"    -> Error: {result}")

    # Remove duplicates by pc (photo hash)
    seen = set()
    unique_photos = []
    for ph in all_photos:
        pc = ph.get('pc')
        if pc and pc not in seen:
            seen.add(pc)
            unique_photos.append(ph)

    total = len(unique_photos)
    print(f"\n[2/3] Total unique photos: {total}")
    if not unique_photos:
        browser.close()
        exit(1)

    unique_photos.sort(key=lambda x: x.get("i", 0))

    success = 0
    failed = 0
    skipped = 0

    for idx, ph in enumerate(unique_photos, 1):
        img_url = ph.get("ol") or ph.get("bl") or ph.get("sl") or ph.get("url1920")
        if not img_url:
            failed += 1
            continue

        raw_name = ph.get("n", "")
        if raw_name:
            base = sanitize_filename(raw_name)
        else:
            base = sanitize_filename(ph.get("pc", f"photo_{idx:04d}"))

        if "." not in base:
            ext = ".jpg"
            if ".png" in img_url.lower():
                ext = ".png"
            base += ext

        filepath = Path(OUTPUT_DIR) / base

        if filepath.exists():
            existing_size = filepath.stat().st_size
            expected_size = ph.get("os", 0)
            if expected_size and existing_size == expected_size:
                skipped += 1
                continue
            stem = filepath.stem
            suffix = filepath.suffix
            counter = 1
            while filepath.exists():
                filepath = Path(OUTPUT_DIR) / f"{stem}_{counter:02d}{suffix}"
                counter += 1
            base = filepath.name

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = page.request.get(img_url, timeout=60000)
                if resp.status == 200:
                    body = resp.body()
                    with open(filepath, "wb") as f:
                        f.write(body)
                    success += 1
                    if idx % 10 == 0 or idx == total:
                        print(f"[{idx:>4}/{total}] {base} ({len(body)/1024/1024:.2f} MB)")
                    break
                else:
                    if attempt == MAX_RETRIES:
                        failed += 1
                        print(f"[{idx:>4}/{total}] HTTP {resp.status} - {base}")
                    time.sleep(1)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    failed += 1
                    print(f"[{idx:>4}/{total}] ERROR: {e} - {base}")
                time.sleep(1)

    browser.close()

    print(f"\n{'='*60}")
    print(f"Done!")
    print(f"  Success:  {success}")
    print(f"  Skipped:  {skipped}")
    print(f"  Failed:   {failed}")
    print(f"  Total:    {total}")
    print(f"  Output:   {OUTPUT_DIR}")
    print(f"{'='*60}")
