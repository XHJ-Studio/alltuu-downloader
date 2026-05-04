#!/usr/bin/env python3
"""
alltuu.com (喔图) Album Downloader
Uses Playwright to intercept API calls and download original quality photos.
Target: https://m.alltuu.com/album/1461544002/3712671117?menu=live
"""

import json, os, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── Configuration ────────────────────────────────────────────────────────────
ALBUM_URL = "https://m.alltuu.com/album/1461544002/3712671117?menu=live"
OUTPUT_DIR = r"D:\2024-2025学年全球发明大会中国区全国总决赛"
HEADLESS = True
MAX_RETRIES = 3

# ── Helpers ──────────────────────────────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    """Remove characters illegal in Windows filenames."""
    return re.sub(r'[\\/:*?"<>|]+', "", name).strip()

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

# ── Core ─────────────────────────────────────────────────────────────────────
def download_album():
    ensure_dir(Path(OUTPUT_DIR))

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

        # ── Step 1: Capture fplN API URL ─────────────────────────────────────
        state = {"fplN_url": None}
        def handle_route(route, request):
            url = request.url
            if "/rest/v4c/fplN/" in url and state["fplN_url"] is None:
                state["fplN_url"] = url
                print(f"[API] Captured photo list endpoint")
            route.continue_()

        page.route("**/*", handle_route)

        print(f"[1/4] Navigating to album page...")
        page.goto(ALBUM_URL, wait_until="domcontentloaded", timeout=30000)

        # Wait for the API call (with gentle scrolling to trigger lazy-load)
        for i in range(15):
            time.sleep(1)
            if state["fplN_url"]:
                break
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

        if not state["fplN_url"]:
            print("[ERROR] Failed to capture photo list API URL. Exiting.")
            browser.close()
            return

        # ── Step 2: Fetch photo list via in-page fetch ───────────────────────
        print(f"[2/4] Fetching photo list...")
        result = page.evaluate("""
            async (url) => {
                const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
                if (!resp.ok) return {error: resp.status, text: await resp.text()};
                return await resp.json();
            }
        """, state["fplN_url"])

        if isinstance(result, dict) and 'error' in result:
            print(f"[ERROR] API error {result['error']}: {result.get('text', '')[:200]}")
            browser.close()
            return

        photos = result.get("d", [])
        total = len(photos)
        print(f"[2/4] Found {total} photos")
        if not photos:
            browser.close()
            return

        # Sort by index to maintain order
        photos.sort(key=lambda x: x.get("i", 0))

        # ── Step 3: Download images ──────────────────────────────────────────
        print(f"[3/4] Downloading to: {OUTPUT_DIR}")
        success = 0
        failed = 0
        skipped = 0

        for idx, ph in enumerate(photos, 1):
            img_url = ph.get("ol") or ph.get("bl") or ph.get("sl") or ph.get("url1920")
            if not img_url:
                print(f"[{idx:>3}/{total}] SKIP: no URL")
                failed += 1
                continue

            # Build filename
            raw_name = ph.get("n", "")
            if raw_name:
                base = sanitize_filename(raw_name)
            else:
                base = sanitize_filename(ph.get("pc", f"photo_{idx:04d}"))

            # Ensure extension
            if "." not in base:
                ext = ".jpg"
                if ".png" in img_url.lower():
                    ext = ".png"
                base += ext

            filepath = Path(OUTPUT_DIR) / base

            # Handle duplicates
            if filepath.exists():
                # Check if file size matches (if available)
                existing_size = filepath.stat().st_size
                expected_size = ph.get("os", 0)
                if expected_size and existing_size == expected_size:
                    print(f"[{idx:>3}/{total}] EXISTS (verified): {base}")
                    skipped += 1
                    continue
                # Otherwise rename
                stem = filepath.stem
                suffix = filepath.suffix
                counter = 1
                while filepath.exists():
                    filepath = Path(OUTPUT_DIR) / f"{stem}_{counter:02d}{suffix}"
                    counter += 1
                base = filepath.name

            # Download with retry
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = page.request.get(img_url, timeout=60000)
                    if resp.status == 200:
                        body = resp.body()
                        with open(filepath, "wb") as f:
                            f.write(body)
                        size_mb = len(body) / 1024 / 1024
                        print(f"[{idx:>3}/{total}] OK {base} ({size_mb:.2f} MB)")
                        success += 1
                        break
                    else:
                        print(f"[{idx:>3}/{total}] HTTP {resp.status} (attempt {attempt})")
                        if attempt == MAX_RETRIES:
                            failed += 1
                        time.sleep(1)
                except Exception as e:
                    print(f"[{idx:>3}/{total}] ERROR (attempt {attempt}): {e}")
                    if attempt == MAX_RETRIES:
                        failed += 1
                    time.sleep(1)

        browser.close()

        # ── Step 4: Summary ──────────────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"Done!")
        print(f"  Success:  {success}")
        print(f"  Skipped:  {skipped}")
        print(f"  Failed:   {failed}")
        print(f"  Total:    {total}")
        print(f"  Output:   {OUTPUT_DIR}")
        print(f"{'='*60}")

if __name__ == "__main__":
    download_album()
