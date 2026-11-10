"""MERRA-2 Aerosol Optical Depth Downloader via OPeNDAP Server-Side Subsetting.

Subsets only the total aerosol optical depth variable (TOTEXTTAU), lat, lon, and time
directly from the NASA GES DISC OPeNDAP server.
This reduces the dataset from 20.1 GB down to ~220 MB total (~714 KB per month).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import earthaccess
from auth import login_earthdata


TARGET_DIR = Path("data/raw/merra2_aod")
TARGET_DIR.mkdir(parents=True, exist_ok=True)

SHORT_NAME = "M2TMNXAER"
VERSION = "5.12.4"
START_DATE = "2000-06-01"
END_DATE = "2025-09-01"
OPENDAP_COLLECTION = "C1276812866-GES_DISC"


def get_granule_list():
    """Query CMR for MERRA-2 monthly aerosol granules."""
    print(f"[*] Querying Earthdata CMR for {SHORT_NAME} v{VERSION}...")
    granules = earthaccess.search_data(
        short_name=SHORT_NAME,
        version=VERSION,
        temporal=(START_DATE, END_DATE),
    )
    return sorted(granules, key=lambda g: g["meta"].get("native-id", ""))


def download_single_opendap_granule(args) -> bool:
    """Download single month subset via OPeNDAP."""
    session, opendap_base_url, target_file = args
    if target_file.exists() and target_file.stat().st_size > 50_000:
        return True

    url = f"{opendap_base_url}.nc4?TOTEXTTAU,lat,lon,time"
    tmp_file = target_file.with_suffix(".tmp")
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 50_000:
                with open(tmp_file, "wb") as f:
                    f.write(resp.content)
                tmp_file.replace(target_file)
                return True
            else:
                time.sleep(1.0)
        except Exception:
            time.sleep(1.0)

    if tmp_file.exists():
        tmp_file.unlink()
    return False


def fetch_merra2_aerosols(limit: int | None = None) -> int:
    """Download MERRA-2 AOD granules via OPeNDAP."""
    login_earthdata()
    granules = get_granule_list()
    if not granules:
        print("[-] No granules found for MERRA-2.")
        return 1

    print(f"[*] Found {len(granules)} monthly granules.")
    session = earthaccess.get_requests_https_session()

    items = []
    for g in granules:
        native_id = g["meta"]["native-id"]
        fname = native_id.split(":")[-1] if ":" in native_id else native_id
        target_path = TARGET_DIR / fname

        opendap_url = None
        for u in g["umm"].get("RelatedUrls", []):
            if "opendap" in u.get("URL", "").lower():
                opendap_url = u["URL"]
                break

        if opendap_url:
            items.append((session, opendap_url, target_path))

    already_done = [item for item in items if item[2].exists() and item[2].stat().st_size > 50_000]
    to_download = [item for item in items if not (item[2].exists() and item[2].stat().st_size > 50_000)]

    print(f"[*] Verified locally on disk : {len(already_done)} / {len(items)} files")
    print(f"[*] Granules remaining       : {len(to_download)} (~{len(to_download) * 0.714:.1f} MB)")

    if limit:
        to_download = to_download[:limit]

    if not to_download:
        print("[+] All MERRA-2 AOD granules already present on disk!")
        return 0

    print(f"[*] Downloading {len(to_download)} granules via OPeNDAP in parallel (threads=6)...")
    t0 = time.time()
    success = len(already_done)

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(download_single_opendap_granule, item): item for item in to_download}
        done_count = 0
        for fut in as_completed(futures):
            done_count += 1
            if fut.result():
                success += 1
            if done_count % 25 == 0 or done_count == len(to_download):
                print(f"    [{done_count}/{len(to_download)}] Progress: {done_count} finished | Elapsed: {time.time() - t0:.1f}s")

    print(f"\n[+] MERRA-2 AOD fetch complete: {success} / {len(items)} files ready.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    sys.exit(fetch_merra2_aerosols(limit=args.limit))
