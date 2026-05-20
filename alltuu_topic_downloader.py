#!/usr/bin/env python3
"""
alltuu Topic Downloader - Downloads all photos from all sub-albums.
Topic URL: https://m.alltuu.com/topic/zh/view/large/1005100537/
Output: D:\2024年深圳渔业博览会
"""
import json, os, re, hashlib, time
from pathlib import Path
from playwright.sync_api import sync_playwright

TOPIC_URL = "https://m.alltuu.com/topic/zh/view/large/1005100537/?from=qrCode&mode=release"
BASE_OUTPUT_DIR = r"D:\2024年深圳渔业博览会"
HEADLESS = True
MAX_RETRIES = 3

# ── Helpers ──────────────────────────────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "", name).strip() or "unnamed"

def file_md5(filepath: Path) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def scan_existing_md5s(base_dir: Path) -> dict:
    md5_map = {}
    for folder in base_dir.iterdir():
        if not folder.is_dir():
            continue
        for f in folder.iterdir():
            if not f.is_file():
                continue
            try:
                md5 = file_md5(f)
                if md5 not in md5_map:
                    md5_map[md5] = f
            except Exception as e:
                print(f"  [WARN] Cannot hash {f.name}: {e}")
    return md5_map

# ── Core ─────────────────────────────────────────────────────────────────────
def get_topic_albums(page):
    """Fetch album list from topic page."""
    api_url = None
    def handle_route(route, request):
        nonlocal api_url
        url = request.url
        if "queryAlbumListInfoByAlbumIdS" in url and api_url is None:
            api_url = url
        route.continue_()

    page.route("**/*", handle_route)
    page.goto(TOPIC_URL, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    try:
        page.click(".poster-close", timeout=3000)
        time.sleep(1)
    except:
        pass

    for _ in range(10):
        if api_url:
            break
        time.sleep(1)

    page.unroute("**/*")

    if not api_url:
        print("[ERROR] Failed to capture album list API")
        return []

    result = page.evaluate("""
        async (url) => {
            const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
            if (!resp.ok) return {error: resp.status};
            return await resp.json();
        }
    """, api_url)

    if not isinstance(result, dict) or "d" not in result:
        return []

    albums = []
    for album in result["d"].get("list", []):
        albums.append({
            "id": str(album.get("id", "")),
            "title": album.get("title", f"album_{album.get('id', '')}"),
        })
    return albums


def get_sub_albums(page, album_id):
    """Fetch sub-albums and photo counts for a single album."""
    album_url = f"https://m.alltuu.com/album/{album_id}"
    fa_data = [None]

    def on_response(response):
        try:
            url = response.url
            if response.status == 200 and "json" in response.headers.get("content-type", ""):
                body = response.body()
                data = json.loads(body)
                if "d" in data:
                    if "/rest/v4c/fa/a" in url and "albumDTO" in data["d"]:
                        if fa_data[0] is None:
                            fa_data[0] = {}
                        fa_data[0].update(data["d"])
                    elif "/rest/v4o/us/a" in url and "s" in data["d"]:
                        if fa_data[0] is None:
                            fa_data[0] = {}
                        fa_data[0]["s"] = data["d"]["s"]
        except:
            pass

    page.on("response", on_response)
    page.goto(album_url, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    try:
        page.click(".poster-close", timeout=3000)
        time.sleep(0.5)
    except:
        pass

    time.sleep(1)
    page.remove_listener("response", on_response)

    if not fa_data[0]:
        return []

    subs = fa_data[0].get("seperateDTOList", [])
    counts = fa_data[0].get("s", {})

    sub_albums = []
    for sub in subs:
        sub_id = str(sub.get("idEnc", ""))
        sub_name = sub.get("name", "")
        count = counts.get(sub_id, {}).get("t", 0) if isinstance(counts.get(sub_id), dict) else 0
        sub_albums.append({"id": sub_id, "name": sub_name, "count": count})

    return sub_albums


def download_sub_album(context, parent_id, sub_id, folder_name, expected_count, existing_md5s: dict):
    """Download all photos from a sub-album."""
    output_dir = Path(BASE_OUTPUT_DIR) / sanitize_filename(folder_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check if already mostly downloaded
    existing_files = len([f for f in output_dir.iterdir() if f.is_file()])
    if existing_files >= expected_count * 0.9 and expected_count > 0:
        print(f"\n  Skipping {folder_name}: {existing_files}/{expected_count} files already exist")
        return 0, 0, 0

    album_url = f"https://m.alltuu.com/album/{parent_id}/{sub_id}?menu=live"
    print(f"\n  Album URL: {album_url}")
    print(f"  Output: {output_dir}")

    page = context.new_page()

    # Capture fplN APIs
    fplN_urls = []
    def handle_route(route, request):
        url = request.url
        if "/rest/v4c/fplN/" in url and url not in fplN_urls:
            fplN_urls.append(url)
        route.continue_()

    page.route("**/*", handle_route)
    page.goto(album_url, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    try:
        page.click(".poster-close", timeout=3000)
        time.sleep(1)
        print("  Closed popup")
    except:
        pass

    # Scroll
    print("  Scrolling...")
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
            if len(fplN_urls) % 5 == 0:
                print(f"    scroll {i+1}: fplN={len(fplN_urls)}")
        else:
            stall_count += 1
            if stall_count >= 30 and len(fplN_urls) > 0:
                print(f"    Stopped after {stall_count} stall scrolls")
                break

    time.sleep(1)
    page.unroute("**/*")

    if not fplN_urls:
        print("  [ERROR] No fplN API captured")
        page.close()
        return 0, 0, 0

    print(f"  Captured {len(fplN_urls)} fplN APIs")

    # Fetch all photos
    all_photos = []
    for api_url in fplN_urls:
        result = page.evaluate("""
            async (url) => {
                const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
                if (!resp.ok) return {error: resp.status};
                return await resp.json();
            }
        """, api_url)

        if isinstance(result, dict) and "error" in result:
            continue
        photos = result.get("d", [])
        all_photos.extend(photos)

    # Deduplicate by pc
    seen_pc = set()
    unique_photos = []
    for ph in all_photos:
        pc = ph.get("pc")
        if pc and pc not in seen_pc:
            seen_pc.add(pc)
            unique_photos.append(ph)

    total = len(unique_photos)
    print(f"  Total unique: {total}")

    # Download
    success = 0
    failed = 0
    skipped = 0
    new_md5s = {}

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

        filepath = output_dir / base

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = page.request.get(img_url, timeout=60000)
                if resp.status == 200:
                    body = resp.body()
                    md5 = hashlib.md5(body).hexdigest()

                    if md5 in existing_md5s or md5 in new_md5s:
                        skipped += 1
                        if idx % 50 == 0 or idx == total:
                            print(f"    [{idx}/{total}] SKIP {base}")
                        break

                    with open(filepath, "wb") as f:
                        f.write(body)
                    new_md5s[md5] = filepath
                    success += 1
                    if idx % 10 == 0 or idx == total:
                        print(f"    [{idx}/{total}] {base} ({len(body)/1024/1024:.2f} MB)")
                    break
                else:
                    if attempt == MAX_RETRIES:
                        failed += 1
                        print(f"    [{idx}/{total}] HTTP {resp.status} - {base}")
                    time.sleep(1)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    failed += 1
                    print(f"    [{idx}/{total}] ERROR: {e} - {base}")
                time.sleep(1)

    page.close()
    print(f"  -> Success: {success}, Skipped: {skipped}, Failed: {failed}")
    existing_md5s.update(new_md5s)
    return success, failed, total


def remove_duplicate_files():
    base = Path(BASE_OUTPUT_DIR)
    if not base.exists():
        return 0

    total_removed = 0
    print("\n" + "=" * 60)
    print("Removing duplicates...")
    print("=" * 60)

    for folder in base.iterdir():
        if not folder.is_dir():
            continue

        hashes = {}
        dups = []
        for f in folder.iterdir():
            if not f.is_file():
                continue
            try:
                md5 = file_md5(f)
                if md5 in hashes:
                    dups.append((f, hashes[md5]))
                else:
                    hashes[md5] = f
            except:
                pass

        for dup, orig in dups:
            try:
                dup.unlink()
                total_removed += 1
                print(f"  [REMOVED] {folder.name}/{dup.name}")
            except:
                pass

        if dups:
            print(f"  {folder.name}: removed {len(dups)}, kept {len(hashes)}")

    print(f"\nTotal removed: {total_removed}")
    return total_removed


def print_report():
    base = Path(BASE_OUTPUT_DIR)
    if not base.exists():
        return

    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)

    total_files = 0
    total_size = 0
    for folder in sorted(base.iterdir()):
        if not folder.is_dir():
            continue
        files = [f for f in folder.iterdir() if f.is_file()]
        size = sum(f.stat().st_size for f in files)
        total_files += len(files)
        total_size += size
        print(f"  {folder.name:40s}: {len(files):>4} files, {size/1024/1024:>8.1f} MB")

    print("-" * 60)
    print(f"  {'TOTAL':40s}: {total_files:>4} files, {total_size/1024/1024/1024:>8.2f} GB")
    print("=" * 60)


def main():
    Path(BASE_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    # Pre-scan existing files
    print("=" * 60)
    print("Scanning existing files...")
    print("=" * 60)
    existing_md5s = scan_existing_md5s(Path(BASE_OUTPUT_DIR))
    print(f"Found {len(existing_md5s)} unique existing files")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
                       "Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
            device_scale_factor=3,
        )

        # Step 1: Get topic albums
        print("\n" + "=" * 60)
        print("Step 1: Fetching topic albums...")
        print("=" * 60)
        page = context.new_page()
        albums = get_topic_albums(page)
        page.close()

        if not albums:
            print("Failed to get albums. Exiting.")
            browser.close()
            return

        print(f"Found {len(albums)} albums")
        for a in albums:
            print(f"  {a['id']}: {a['title']}")

        # Step 2: For each album, get sub-albums and download
        print("\n" + "=" * 60)
        print("Step 2: Downloading...")
        print("=" * 60)

        grand_success = 0
        grand_failed = 0
        grand_total = 0

        for idx, album in enumerate(albums, 1):
            print(f"\n[{idx}/{len(albums)}] Album: {album['title']}")

            # Get sub-albums
            page = context.new_page()
            sub_albums = get_sub_albums(page, album["id"])
            page.close()

            if not sub_albums:
                print(f"  [WARN] No sub-albums found, trying album itself...")
                sub_albums = [{"id": album["id"], "name": "图片直播", "count": 0}]

            print(f"  Sub-albums: {len(sub_albums)}")
            for sub in sub_albums:
                print(f"    -> {sub['name']} ({sub['count']} photos)")

            # Determine folder naming
            if len(sub_albums) == 1:
                # Single sub-album: use album title as folder
                sub = sub_albums[0]
                s, f, t = download_sub_album(context, album["id"], sub["id"], album["title"], sub["count"], existing_md5s)
                grand_success += s
                grand_failed += f
                grand_total += t
            else:
                # Multiple sub-albums: use sub-album names as folders
                for sub in sub_albums:
                    s, f, t = download_sub_album(context, album["id"], sub["id"], sub["name"], sub["count"], existing_md5s)
                    grand_success += s
                    grand_failed += f
                    grand_total += t

        browser.close()

    # Step 3: Remove duplicates
    remove_duplicate_files()

    # Step 4: Report
    print_report()

    print("\n" + "=" * 60)
    print("ALL DONE!")
    print(f"  Success: {grand_success}")
    print(f"  Failed:  {grand_failed}")
    print(f"  Total:   {grand_total}")
    print("=" * 60)


if __name__ == "__main__":
    main()
