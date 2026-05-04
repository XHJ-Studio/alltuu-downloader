#!/usr/bin/env python3
"""
alltuu.com (喔图) Batch Album Downloader
Downloads all sub-albums from a parent album into organized folders.
"""

import json, os, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── Configuration ────────────────────────────────────────────────────────────
PARENT_ALBUM_URL = "https://m.alltuu.com/album/1461544002"
BASE_OUTPUT_DIR = r"D:\2024-2025学年全球发明大会中国区全国总决赛"
HEADLESS = True
MAX_RETRIES = 3
API_TIMEOUT = 30000
IMG_TIMEOUT = 60000

# ── Helpers ──────────────────────────────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "", name).strip() or "unnamed"

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def log(msg):
    print(msg, flush=True)

# ── Core ─────────────────────────────────────────────────────────────────────
def fetch_sub_album_list(context):
    """Fetch sub-album list from parent album page."""
    page = context.new_page()
    state = {"fa_url": None}
    def handle_route(route, request):
        url = request.url
        if "/rest/v4c/fa/a" in url and state["fa_url"] is None:
            state["fa_url"] = url
        route.continue_()

    page.route("**/*", handle_route)
    page.goto(PARENT_ALBUM_URL, wait_until="domcontentloaded", timeout=API_TIMEOUT)

    for i in range(10):
        time.sleep(1)
        if state["fa_url"]:
            break
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    page.unroute("**/*")

    if not state["fa_url"]:
        log("[ERROR] Failed to capture album info API")
        page.close()
        return []

    result = page.evaluate("""
        async (url) => {
            const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
            if (!resp.ok) return {error: resp.status};
            return await resp.json();
        }
    """, state["fa_url"])

    page.close()

    if not isinstance(result, dict) or 'd' not in result:
        log("[ERROR] Invalid album info response")
        return []

    subs = result['d'].get('seperateDTOList', [])
    albums = []
    for sub in subs:
        albums.append({
            'id': str(sub.get('idEnc', '')),
            'name': sub.get('name', f"album_{sub.get('idEnc', '')}"),
            'seq': sub.get('seq', 0),
        })
    albums.sort(key=lambda x: x['seq'])
    return albums


def download_photos_from_api(page, fplN_url, output_dir):
    """Download all photos from a single fplN API URL."""
    log(f"    Fetching photo list...")
    result = page.evaluate("""
        async (url) => {
            const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
            if (!resp.ok) return {error: resp.status, text: await resp.text()};
            return await resp.json();
        }
    """, fplN_url)

    if isinstance(result, dict) and 'error' in result:
        log(f"    [ERROR] API error {result['error']}")
        return (0, 0, 0, 0)

    photos = result.get("d", [])
    total = len(photos)
    if not photos:
        return (0, 0, 0, 0)

    photos.sort(key=lambda x: x.get("i", 0))
    log(f"    Downloading {total} photos...")

    success = 0
    failed = 0
    skipped = 0

    for idx, ph in enumerate(photos, 1):
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

        filepath = Path(output_dir) / base

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
                filepath = Path(output_dir) / f"{stem}_{counter:02d}{suffix}"
                counter += 1
            base = filepath.name

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = page.request.get(img_url, timeout=IMG_TIMEOUT)
                if resp.status == 200:
                    body = resp.body()
                    with open(filepath, "wb") as f:
                        f.write(body)
                    success += 1
                    if idx % 10 == 0 or idx == total:
                        log(f"      [{idx}/{total}] {base} ({len(body)/1024/1024:.2f} MB)")
                    break
                else:
                    if attempt == MAX_RETRIES:
                        failed += 1
                        log(f"      [{idx}/{total}] HTTP {resp.status} - {base}")
                    time.sleep(1)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    failed += 1
                    log(f"      [{idx}/{total}] ERROR: {e} - {base}")
                time.sleep(1)

    return (success, failed, total, skipped)


def download_sub_album(context, sub_album):
    """Download all photos from a sub-album, handling pagination."""
    sub_id = sub_album['id']
    sub_name = sub_album['name']
    folder_name = f"{sub_album['seq']+1:02d}. {sanitize_filename(sub_name)}"
    output_dir = os.path.join(BASE_OUTPUT_DIR, folder_name)
    ensure_dir(Path(output_dir))

    album_url = f"https://m.alltuu.com/album/1461544002/{sub_id}?menu=live"
    log(f"\n  Album: {sub_name}")
    log(f"  URL: {album_url}")
    log(f"  Output: {output_dir}")

    page = context.new_page()

    # Capture all fplN API URLs (for pagination)
    fplN_urls = []
    def handle_route(route, request):
        url = request.url
        if "/rest/v4c/fplN/" in url and url not in fplN_urls:
            fplN_urls.append(url)
            log(f"    [API] Captured fplN #{len(fplN_urls)}")
        route.continue_()

    page.route("**/*", handle_route)
    log("  Navigating...")
    page.goto(album_url, wait_until="domcontentloaded", timeout=API_TIMEOUT)
    log("  DOM ready, scrolling...")

    # Wait and scroll to trigger all API calls
    prev_count = 0
    stall_count = 0
    for i in range(30):
        time.sleep(1)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        if len(fplN_urls) > prev_count:
            prev_count = len(fplN_urls)
            stall_count = 0
        else:
            stall_count += 1
        if stall_count >= 5 and len(fplN_urls) > 0:
            break

    time.sleep(1)
    page.unroute("**/*")

    if not fplN_urls:
        log(f"  [ERROR] No photo list API captured")
        page.close()
        return (0, 0, 0, 0)

    # Download photos from all captured API URLs
    total_success = 0
    total_failed = 0
    total_photos = 0
    total_skipped = 0

    for api_url in fplN_urls:
        s, f, t, sk = download_photos_from_api(page, api_url, output_dir)
        total_success += s
        total_failed += f
        total_photos += t
        total_skipped += sk

    page.close()
    log(f"  -> Success: {total_success}, Skipped: {total_skipped}, Failed: {total_failed}, Total: {total_photos}")
    return (total_success, total_failed, total_photos, total_skipped)


def main():
    ensure_dir(Path(BASE_OUTPUT_DIR))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
                       "Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
            device_scale_factor=3,
        )

        # Step 1: Get sub-album list
        log("=" * 60)
        log("Step 1: Fetching sub-album list...")
        log("=" * 60)
        albums = fetch_sub_album_list(context)
        if not albums:
            log("Failed to get sub-album list. Exiting.")
            browser.close()
            return

        log(f"Found {len(albums)} sub-albums:")
        for a in albums:
            log(f"  [{a['seq']+1}] {a['id']}: {a['name']}")

        # Step 2: Download each sub-album
        log("\n" + "=" * 60)
        log("Step 2: Downloading photos...")
        log("=" * 60)

        grand_success = 0
        grand_failed = 0
        grand_total = 0
        grand_skipped = 0

        for idx, album in enumerate(albums, 1):
            log(f"\n[{idx}/{len(albums)}] Processing sub-album {album['id']}...")
            s, f, t, sk = download_sub_album(context, album)
            grand_success += s
            grand_failed += f
            grand_total += t
            grand_skipped += sk

        browser.close()

    log("\n" + "=" * 60)
    log("ALL DONE!")
    log(f"  Total Success:  {grand_success}")
    log(f"  Total Skipped:  {grand_skipped}")
    log(f"  Total Failed:   {grand_failed}")
    log(f"  Total Photos:   {grand_total}")
    log(f"  Output:         {BASE_OUTPUT_DIR}")
    log("=" * 60)


if __name__ == "__main__":
    main()
