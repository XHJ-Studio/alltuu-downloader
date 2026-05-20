#!/usr/bin/env python3
"""
alltuu.com Full Album Re-download with Duplicate Removal
Downloads all photos from all sub-albums, skipping existing files by MD5.
"""
import json, os, re, hashlib, time
from pathlib import Path
from playwright.sync_api import sync_playwright

PARENT_ALBUM_URL = "https://m.alltuu.com/album/1461544002"
BASE_OUTPUT_DIR = r"D:\2024-2025学年全球发明大会中国区全国总决赛"
HEADLESS = True
MAX_RETRIES = 3

# ── Helpers ──────────────────────────────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "", name).strip() or "unnamed"

def file_md5(filepath: Path) -> str:
    """Compute MD5 hash of a file."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def scan_existing_md5s(base_dir: Path) -> dict:
    """Scan all existing files and build md5 -> filepath mapping."""
    md5_map = {}
    for folder in base_dir.iterdir():
        if not folder.is_dir():
            continue
        for f in folder.iterdir():
            if not f.is_file():
                continue
            try:
                md5 = file_md5(f)
                if md5 in md5_map:
                    print(f"  [WARN] Duplicate found: {f.name} == {md5_map[md5].name}")
                else:
                    md5_map[md5] = f
            except Exception as e:
                print(f"  [WARN] Cannot hash {f.name}: {e}")
    return md5_map

# ── Core ─────────────────────────────────────────────────────────────────────
def get_sub_albums(page):
    """Fetch sub-album list from parent album page."""
    state = {"fa_url": None}
    def handle_route(route, request):
        url = request.url
        if "/rest/v4c/fa/a" in url and state["fa_url"] is None:
            state["fa_url"] = url
        route.continue_()

    page.route("**/*", handle_route)
    page.goto(PARENT_ALBUM_URL, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    # Close popup if present
    try:
        page.click(".poster-close", timeout=3000)
        time.sleep(1)
    except:
        pass

    for _ in range(10):
        if state["fa_url"]:
            break
        time.sleep(1)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    page.unroute("**/*")

    if not state["fa_url"]:
        print("[ERROR] Failed to capture album info API")
        return []

    result = page.evaluate("""
        async (url) => {
            const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
            if (!resp.ok) return {error: resp.status};
            return await resp.json();
        }
    """, state["fa_url"])

    if not isinstance(result, dict) or "d" not in result:
        print("[ERROR] Invalid album info response")
        return []

    subs = result["d"].get("seperateDTOList", [])
    albums = []
    for sub in subs:
        albums.append({
            "id": str(sub.get("idEnc", "")),
            "name": sub.get("name", f"album_{sub.get('idEnc', '')}"),
            "seq": sub.get("seq", 0),
        })
    albums.sort(key=lambda x: x["seq"])
    return albums


def download_sub_album(context, sub_album, existing_md5s: dict):
    """Download all photos from a sub-album."""
    sub_id = sub_album["id"]
    sub_name = sub_album["name"]
    output_dir = Path(BASE_OUTPUT_DIR) / sanitize_filename(sub_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    album_url = f"https://m.alltuu.com/album/1461544002/{sub_id}?menu=live"
    print(f"\n  Album: {sub_name}")
    print(f"  URL: {album_url}")
    print(f"  Output: {output_dir}")

    page = context.new_page()

    # Capture all fplN pagination APIs
    fplN_urls = []
    def handle_route(route, request):
        url = request.url
        if "/rest/v4c/fplN/" in url and url not in fplN_urls:
            fplN_urls.append(url)
        route.continue_()

    page.route("**/*", handle_route)
    print("  Navigating...")
    page.goto(album_url, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    # Close popup
    try:
        page.click(".poster-close", timeout=3000)
        time.sleep(1)
        print("  Closed popup")
    except:
        pass

    # Scroll inside container to trigger lazy loading
    print("  Scrolling to load all pages...")
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
                print(f"    Stopped: no new pages after {stall_count} scrolls")
                break

    time.sleep(1)
    page.unroute("**/*")

    if not fplN_urls:
        print("  [ERROR] No photo list API captured")
        page.close()
        return 0, 0, 0

    print(f"  Captured {len(fplN_urls)} fplN APIs")

    # Fetch all photo lists
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
            print(f"    [WARN] API error {result['error']}: {api_url[:60]}")
            continue

        photos = result.get("d", [])
        all_photos.extend(photos)

    # Deduplicate by pc (photo hash)
    seen_pc = set()
    unique_photos = []
    for ph in all_photos:
        pc = ph.get("pc")
        if pc and pc not in seen_pc:
            seen_pc.add(pc)
            unique_photos.append(ph)

    total = len(unique_photos)
    print(f"  Total unique photos: {total}")

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

        # Download with retry
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = page.request.get(img_url, timeout=60000)
                if resp.status == 200:
                    body = resp.body()

                    # Check MD5 against existing files
                    md5 = hashlib.md5(body).hexdigest()
                    if md5 in existing_md5s:
                        skipped += 1
                        if idx % 50 == 0 or idx == total:
                            print(f"    [{idx}/{total}] SKIP (duplicate) {base}")
                        break

                    # Check against newly downloaded files in this session
                    if md5 in new_md5s:
                        skipped += 1
                        if idx % 50 == 0 or idx == total:
                            print(f"    [{idx}/{total}] SKIP (session dup) {base}")
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
    print(f"  -> Success: {success}, Skipped: {skipped}, Failed: {failed}, Total: {total}")

    # Update global md5 map with new files
    existing_md5s.update(new_md5s)
    return success, failed, total


def remove_duplicate_files():
    """Scan all folders and remove duplicate files by MD5."""
    base = Path(BASE_OUTPUT_DIR)
    if not base.exists():
        return 0

    total_removed = 0
    print("\n" + "=" * 60)
    print("Removing duplicate files by MD5...")
    print("=" * 60)

    for folder in base.iterdir():
        if not folder.is_dir():
            continue

        hashes = {}
        duplicates = []
        for f in folder.iterdir():
            if not f.is_file():
                continue
            try:
                md5 = file_md5(f)
                if md5 in hashes:
                    duplicates.append((f, hashes[md5]))
                else:
                    hashes[md5] = f
            except Exception as e:
                print(f"  [WARN] Cannot read {f.name}: {e}")

        for dup, original in duplicates:
            try:
                dup.unlink()
                total_removed += 1
                print(f"  [REMOVED] {folder.name}/{dup.name} (dup of {original.name})")
            except Exception as e:
                print(f"  [ERROR] Cannot remove {dup.name}: {e}")

        if duplicates:
            print(f"  {folder.name}: removed {len(duplicates)} duplicates, kept {len(hashes)} unique")

    print(f"\nTotal duplicates removed: {total_removed}")
    return total_removed


def print_final_report():
    """Print final file counts per folder."""
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
    print("Scanning existing files for duplicates...")
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

        # Step 1: Get sub-album list
        print("\n" + "=" * 60)
        print("Step 1: Fetching sub-album list...")
        print("=" * 60)
        page = context.new_page()
        albums = get_sub_albums(page)
        page.close()

        if not albums:
            print("Failed to get sub-album list. Exiting.")
            browser.close()
            return

        print(f"Found {len(albums)} sub-albums:")
        for a in albums:
            print(f"  [{a['seq']+1}] {a['id']}: {a['name']}")

        # Step 2: Download each sub-album
        print("\n" + "=" * 60)
        print("Step 2: Downloading photos...")
        print("=" * 60)

        grand_success = 0
        grand_failed = 0
        grand_total = 0

        for idx, album in enumerate(albums, 1):
            print(f"\n[{idx}/{len(albums)}] Processing sub-album {album['id']}...")
            s, f, t = download_sub_album(context, album, existing_md5s)
            grand_success += s
            grand_failed += f
            grand_total += t

        browser.close()

    # Step 3: Remove duplicates
    remove_duplicate_files()

    # Step 4: Report
    print_final_report()

    print("\n" + "=" * 60)
    print("ALL DONE!")
    print(f"  Total Success:  {grand_success}")
    print(f"  Total Failed:   {grand_failed}")
    print(f"  Total Photos:   {grand_total}")
    print("=" * 60)


if __name__ == "__main__":
    main()
