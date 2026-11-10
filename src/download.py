"""Bulk downloader for NASA GPM IMERG V07 Monthly Precipitation Granules.

Includes an in-place, self-deleting animated terminal loading screen that tracks
live download bytes, transfer speed, and progress, and cleanly clears itself upon completion.
"""

from __future__ import annotations

import argparse
import glob
import itertools
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import earthaccess
import xarray as xr

from auth import login_earthdata


RAW_DATA_DIR = Path("data/raw")
MANIFEST_PATH = RAW_DATA_DIR / "download_manifest.json"
SHORT_NAME = "GPM_3IMERGM"
VERSION = "07"
START_DATE = "2000-06-01"
END_DATE = "2026-01-01"


class SelfDeletingProgressScreen:
    """Dynamic terminal loading screen that updates in place and erases itself upon finish."""

    def __init__(self, title: str, expected_size_mb: float = 18.2):
        self.title = title
        self.expected_size_bytes = int(expected_size_mb * 1024 * 1024)
        self.spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.start_time = time.time()
        self.target_dir = RAW_DATA_DIR

    def _get_current_download_bytes(self) -> int:
        """Find the most recently modified partial or destination file in RAW_DATA_DIR."""
        try:
            partial_files = list(self.target_dir.glob("partial_*")) + list(self.target_dir.glob("*.tmp"))
            if partial_files:
                newest = max(partial_files, key=lambda p: p.stat().st_mtime)
                return newest.stat().st_size
        except Exception:
            pass
        return 0

    def _animate(self) -> None:
        last_bytes = 0
        last_time = time.time()
        speed_kb_s = 0.0

        while not self._stop_event.is_set():
            char = next(self.spinner)
            curr_time = time.time()
            elapsed = curr_time - self.start_time

            curr_bytes = self._get_current_download_bytes()
            if curr_bytes > last_bytes and (curr_time - last_time) >= 0.5:
                speed_kb_s = ((curr_bytes - last_bytes) / 1024.0) / (curr_time - last_time)
                last_bytes = curr_bytes
                last_time = curr_time

            # Compute percentage & progress bar
            pct = min(100.0, (curr_bytes / self.expected_size_bytes) * 100.0) if self.expected_size_bytes > 0 else 0.0
            filled_slots = int(pct / 5)  # 20 slot bar
            bar = "━" * filled_slots + "╸" + " " * max(0, 19 - filled_slots)

            # Build in-place status line
            status = (
                f"\r\033[K\033[1;36m{char}\033[0m {self.title} "
                f"\033[36m[{bar}]\033[0m \033[1m{pct:4.1f}%\033[0m "
                f"({curr_bytes / (1024*1024):4.1f}/{self.expected_size_bytes / (1024*1024):4.1f} MB) "
                f"\033[33m{speed_kb_s:5.1f} kB/s\033[0m "
                f"\033[90m[{int(elapsed)}s]\033[0m"
            )

            sys.stdout.write(status)
            sys.stdout.flush()
            time.sleep(0.08)

    def __enter__(self) -> "SelfDeletingProgressScreen":
        self._stop_event.clear()
        self.start_time = time.time()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        # Erase line completely from the terminal buffer
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


def load_manifest() -> dict[str, Any]:
    """Load the progress tracking manifest from disk."""
    if MANIFEST_PATH.exists():
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_manifest(manifest: dict[str, Any]) -> None:
    """Save the progress tracking manifest atomically to disk."""
    temp_manifest = MANIFEST_PATH.with_suffix(".tmp")
    with open(temp_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    temp_manifest.replace(MANIFEST_PATH)


def verify_downloaded_granule(file_path: Path) -> bool:
    """Quick sanity check that granule is non-empty and contains the precipitation variable."""
    if not file_path.exists() or file_path.stat().st_size < 1_000_000:
        return False
    try:
        with xr.open_dataset(file_path, group="Grid", engine="netcdf4") as ds:
            return "precipitation" in ds
    except Exception:
        try:
            with xr.open_dataset(file_path, group="Grid", engine="h5netcdf") as ds:
                return "precipitation" in ds
        except Exception:
            return False


def query_granules() -> list[Any]:
    """Query CMR for all granules in the target window."""
    with SelfDeletingProgressScreen("Querying Earthdata CMR metadata...", expected_size_mb=1.0):
        granules = earthaccess.search_data(
            short_name=SHORT_NAME,
            version=VERSION,
            temporal=(START_DATE, END_DATE),
        )
        granules = sorted(granules, key=lambda g: g["meta"].get("native-id", ""))
    return granules


def download_single_granule_with_retry(
    granule: Any,
    target_dir: Path,
    idx_str: str,
    max_retries: int = 5,
    backoff_factor: float = 2.0,
) -> Path | None:
    """Download a single granule using the animated self-deleting loading screen."""
    native_id = granule["meta"]["native-id"]
    expected_filename = native_id.split(":")[-1] if ":" in native_id else native_id
    final_path = target_dir / expected_filename
    granule_size_mb = float(granule.get("size", 18.2) or 18.2)

    # If file exists and is valid, skip
    if final_path.exists() and verify_downloaded_granule(final_path):
        return final_path

    for attempt in range(1, max_retries + 1):
        start_t = time.time()
        title = f"[{idx_str}] Fetching {expected_filename[:35]}..."

        # THE IN-PLACE SELF-DELETING LOADING SCREEN
        with SelfDeletingProgressScreen(title, expected_size_mb=granule_size_mb):
            try:
                files = earthaccess.download(granule, str(target_dir))
            except Exception:
                files = None

        dur = time.time() - start_t

        if files and Path(files[0]).exists():
            downloaded = Path(files[0])
            if verify_downloaded_granule(downloaded):
                # Clean persistent success entry replacing the erased loading screen
                size_mb = downloaded.stat().st_size / (1024 * 1024)
                sys.stdout.write(
                    f"\033[32m✔\033[0m [{idx_str}] \033[1m{downloaded.name}\033[0m "
                    f"({size_mb:.2f} MB) in \033[33m{dur:.1f}s\033[0m\n"
                )
                sys.stdout.flush()
                return downloaded
            else:
                downloaded.unlink(missing_ok=True)

        if attempt < max_retries:
            wait_time = backoff_factor ** attempt
            sys.stdout.write(f"\033[31m!\033[0m [{idx_str}] Attempt {attempt} failed. Retrying in {wait_time:.1f}s...\n")
            sys.stdout.flush()
            time.sleep(wait_time)

    sys.stdout.write(f"\033[31m✖\033[0m [{idx_str}] FAILED {expected_filename}\n")
    sys.stdout.flush()
    return None


def run_pipeline(dry_run: bool = False, limit: int | None = None) -> int:
    """Main execution workflow."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    granules = query_granules()
    total_granules = len(granules)

    if total_granules == 0:
        print("[-] No granules found. Please verify query parameters.")
        return 1

    first_id = granules[0]["meta"]["native-id"]
    last_id = granules[-1]["meta"]["native-id"]
    total_size_mb = sum(float(g.get("size", 18.2) or 18.2) for g in granules)

    print("\n" + "═" * 70)
    print(" 🛰  GPM IMERG V07 MONTHLY INGESTION PIPELINE")
    print("═" * 70)
    print(f" Catalog Count      : {total_granules} granules ({START_DATE} to {END_DATE})")
    print(f" Total Record Range : {first_id.split(':')[-1][:27]} ➔ {last_id.split(':')[-1][:27]}")
    print(f" Estimated Volume   : {total_size_mb:.1f} MB (~{total_size_mb / 1024:.2f} GB)")
    print(f" Target Variable    : 'precipitation' (Grid group)")
    print("═" * 70 + "\n")

    # Fast verification of already-downloaded granules
    already_present: set[str] = set()
    existing_files = list(RAW_DATA_DIR.glob("*.HDF5"))
    print(f"[*] Auditing {len(existing_files)} existing local files in {RAW_DATA_DIR}...")
    for path in existing_files:
        fname = path.name
        if verify_downloaded_granule(path):
            already_present.add(fname)
            manifest[fname] = {
                "status": "completed",
                "size_bytes": path.stat().st_size,
                "verified_at": datetime.utcnow().isoformat(),
            }

    save_manifest(manifest)

    remaining_granules = [
        g for g in granules
        if (g["meta"]["native-id"].split(":")[-1] if ":" in g["meta"]["native-id"] else g["meta"]["native-id"]) not in already_present
    ]

    print(f"[+] Verified on disk : {len(already_present)} / {total_granules} complete")
    print(f"[*] Remaining to get : {len(remaining_granules)} granules")

    if dry_run:
        print("[+] Dry run mode: exiting without downloading.")
        return 0

    if not remaining_granules:
        print("\n\033[32m✔ All granules are already downloaded and verified on disk!\033[0m")
        return 0

    try:
        login_earthdata()
    except Exception as exc:
        print(f"[-] Authentication failed: {exc}", file=sys.stderr)
        return 1

    granules_to_process = remaining_granules[:limit] if limit else remaining_granules
    print(f"[*] Starting download sequence for {len(granules_to_process)} granules...\n")

    success_count = 0
    fail_count = 0

    for idx, granule in enumerate(granules_to_process, start=1):
        native_id = granule["meta"]["native-id"]
        fname = native_id.split(":")[-1] if ":" in native_id else native_id
        idx_str = f"{len(already_present) + idx}/{total_granules}"

        result_path = download_single_granule_with_retry(granule, RAW_DATA_DIR, idx_str=idx_str)
        if result_path and result_path.exists():
            success_count += 1
            manifest[fname] = {
                "status": "completed",
                "size_bytes": result_path.stat().st_size,
                "downloaded_at": datetime.utcnow().isoformat(),
            }
            save_manifest(manifest)
        else:
            fail_count += 1
            manifest[fname] = {
                "status": "failed",
                "attempted_at": datetime.utcnow().isoformat(),
            }
            save_manifest(manifest)

    print("\n" + "═" * 70)
    print(" 🏁 DOWNLOAD COMPLETE")
    print(f" Downloaded this run : {success_count}")
    print(f" Total on disk       : {len(already_present) + success_count} / {total_granules}")
    print("═" * 70)

    return 0 if fail_count == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk download GPM IMERG V07 with self-deleting loading screen.")
    parser.add_argument("--dry-run", action="store_true", help="Report granules and sizes without downloading.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of granules to download in this run.")
    args = parser.parse_args()

    return run_pipeline(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
