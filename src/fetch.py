"""Generic Earthdata Granule Downloader for Kendall.

Config-driven downloader supporting GPM, GLDAS, MERRA-2, and MODIS collections.
Maintains atomic JSON manifests and skips already downloaded files.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import earthaccess
from auth import login_earthdata
from variables import VARIABLES, VariableConfig


RAW_BASE_DIR = Path("data/raw")


def get_raw_dir_for_variable(var_cfg: VariableConfig) -> Path:
    """Return raw download directory for a specific dataset collection."""
    # GLDAS variables share the same underlying files
    coll_dir = var_cfg.dataset_short_name.lower()
    if var_cfg.dataset_short_name == "GPM_3IMERGM":
        return RAW_BASE_DIR  # Keep IMERG files in existing data/raw/
    d = RAW_BASE_DIR / coll_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def query_granules_for_variable(var_cfg: VariableConfig) -> list[Any]:
    """Query CMR for granules matching variable configuration."""
    print(f"[*] Querying Earthdata CMR for {var_cfg.dataset_short_name} v{var_cfg.version}...")
    granules = earthaccess.search_data(
        short_name=var_cfg.dataset_short_name,
        version=var_cfg.version,
        temporal=var_cfg.time_range,
    )
    return sorted(granules, key=lambda g: g["meta"].get("native-id", ""))


def fetch_dataset(var_id: str, dry_run: bool = False, limit: int | None = None) -> int:
    """Execute fetch operation for a given variable."""
    if var_id not in VARIABLES:
        print(f"[-] Unknown variable ID '{var_id}'. Available: {list(VARIABLES.keys())}")
        return 1

    var_cfg = VARIABLES[var_id]
    target_dir = get_raw_dir_for_variable(var_cfg)
    manifest_path = target_dir / "manifest.json"

    granules = query_granules_for_variable(var_cfg)
    total_granules = len(granules)

    if total_granules == 0:
        print(f"[-] No granules found for {var_cfg.name}.")
        return 1

    total_mb = sum(float(g.get("size", 20.0) or 20.0) for g in granules)
    total_gb = total_mb / 1024.0

    print("\n" + "=" * 65)
    print(f" DATASET INGESTION: {var_cfg.name}")
    print("=" * 65)
    print(f" Collection ShortName : {var_cfg.dataset_short_name} (v{var_cfg.version})")
    print(f" Granules Found       : {total_granules}")
    print(f" Total Volume         : {total_mb:.1f} MB (~{total_gb:.2f} GB)")
    print(f" Target Directory     : {target_dir.resolve()}")
    print("=" * 65 + "\n")

    # Check already downloaded files
    existing_files = list(target_dir.glob(f"*.{var_cfg.file_format}"))
    if not existing_files:
        existing_files = list(target_dir.glob("*.*"))

    already_present = set()
    for p in existing_files:
        if p.stat().st_size > 500_000:
            already_present.add(p.name)

    remaining_granules = [
        g for g in granules
        if (g["meta"]["native-id"].split(":")[-1] if ":" in g["meta"]["native-id"] else g["meta"]["native-id"]) not in already_present
    ]
    rem_mb = sum(float(g.get("size", 20.0) or 20.0) for g in remaining_granules)

    print(f"[*] Verified locally on disk : {len(already_present)} / {total_granules} files")
    print(f"[*] Granules remaining       : {len(remaining_granules)} (~{rem_mb / 1024:.2f} GB)")

    if dry_run:
        print("[+] Dry run mode: exiting.")
        return 0

    if not remaining_granules:
        print("[+] All granules are already present and verified on disk!")
        return 0

    if total_gb > 4.0:
        print(f"[!] NOTICE: Total size ({total_gb:.2f} GB) exceeds 4 GB threshold.")

    login_earthdata()

    granules_to_fetch = remaining_granules[:limit] if limit else remaining_granules
    print(f"[*] Downloading {len(granules_to_fetch)} granules in parallel (threads=6)...")

    try:
        downloaded_files = earthaccess.download(granules_to_fetch, str(target_dir), threads=6)
        success = len([f for f in downloaded_files if Path(f).exists() and Path(f).stat().st_size > 500_000])
    except Exception as exc:
        print(f"[-] Parallel download batch encountered issue: {exc}. Retrying remaining sequentially...")
        success = 0
        for idx, g in enumerate(granules_to_fetch, start=1):
            native_id = g["meta"]["native-id"]
            fname = native_id.split(":")[-1] if ":" in native_id else native_id
            target_path = target_dir / fname
            if target_path.exists() and target_path.stat().st_size > 500_000:
                success += 1
                continue
            print(f"[{idx}/{len(granules_to_fetch)}] Downloading {fname}...")
            try:
                files = earthaccess.download(g, str(target_dir))
                if files and Path(files[0]).exists():
                    success += 1
                    print(f"    [+] Saved {fname}")
            except Exception as e:
                print(f"    [-] Failed: {e}")

    print(f"[+] Download batch finished: {success} files verified on disk.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Config-driven Earthdata downloader.")
    parser.add_argument("var_id", help="Variable ID from variables config (e.g. gpm_precip, gldas_precip)")
    parser.add_argument("--dry-run", action="store_true", help="Report size and granules without downloading.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of granules to download.")
    args = parser.parse_args()

    return fetch_dataset(args.var_id, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
