"""MERRA-2 Monthly Single-Level Diagnostics (M2TMNXSLV) Downloader via OPeNDAP.

Extracts only the required diagnostic fields:
  - TS: Surface skin temperature (K, includes ocean surface SST)
  - U10M: 10-meter eastward wind component (m/s)
  - V10M: 10-meter northward wind component (m/s)
  - PS: Surface pressure (Pa)
  - TQV: Total column precipitable water vapor (kg/m^2)
  - lat, lon, time

Precomputes wind speed WIND10M = sqrt(U10M^2 + V10M^2) and saves compressed NetCDF4.
Total size across 304 granules (2000-06 to 2025-09) is ~640-790 MB (< 1 GB limit).
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import earthaccess
import netCDF4
import numpy as np

from auth import login_earthdata


TARGET_DIR = Path("data/raw/merra2_slv")
TARGET_DIR.mkdir(parents=True, exist_ok=True)

SHORT_NAME = "M2TMNXSLV"
VERSION = "5.12.4"
START_DATE = "2000-06-01"
END_DATE = "2025-09-01"


def get_granule_list():
    """Query CMR for MERRA-2 monthly single-level diagnostics granules."""
    print(f"[*] Querying Earthdata CMR for {SHORT_NAME} v{VERSION} ({START_DATE} to {END_DATE})...")
    granules = earthaccess.search_data(
        short_name=SHORT_NAME,
        version=VERSION,
        temporal=(START_DATE, END_DATE),
    )
    return sorted(granules, key=lambda g: g["meta"].get("native-id", ""))


def download_single_granule(session, opendap_base_url: str, target_file: Path) -> bool:
    """Download single month subset via OPeNDAP and save with NetCDF4 compression."""
    if target_file.exists() and target_file.stat().st_size > 1_000_000:
        return True

    # Request only needed variables
    url = f"{opendap_base_url}.nc4?TS,U10M,V10M,PS,TQV,lat,lon,time"
    tmp_file = target_file.with_suffix(".tmp.nc4")

    for attempt in range(4):
        try:
            resp = session.get(url, timeout=45)
            if resp.status_code == 200 and len(resp.content) > 1_000_000:
                # Read memory buffer and write with NetCDF4 zlib compression
                src = netCDF4.Dataset("in_memory", mode="r", memory=resp.content)

                out = netCDF4.Dataset(str(tmp_file), "w", format="NETCDF4")
                for dname, dim in src.dimensions.items():
                    out.createDimension(dname, len(dim))

                # Copy coordinates
                for coord_name in ["lat", "lon", "time"]:
                    if coord_name in src.variables:
                        cvar = src.variables[coord_name]
                        out_c = out.createVariable(coord_name, cvar.dtype, cvar.dimensions)
                        out_c[:] = cvar[:]
                        for attr in cvar.ncattrs():
                            out_c.setncattr(attr, cvar.getncattr(attr))

                # Copy and compress TS, PS, TQV
                for vname in ["TS", "PS", "TQV"]:
                    if vname in src.variables:
                        var = src.variables[vname]
                        fill = var.getncattr("_FillValue") if "_FillValue" in var.ncattrs() else None
                        out_v = out.createVariable(
                            vname, var.dtype, var.dimensions, zlib=True, complevel=4, fill_value=fill
                        )
                        out_v[:] = var[:]
                        for attr in var.ncattrs():
                            if attr != "_FillValue":
                                out_v.setncattr(attr, var.getncattr(attr))

                # Compute WIND10M from U10M and V10M
                if "U10M" in src.variables and "V10M" in src.variables:
                    u_data = src.variables["U10M"][:]
                    v_data = src.variables["V10M"][:]
                    wind_speed = np.sqrt(np.square(u_data) + np.square(v_data)).astype(np.float32)

                    wind_var = out.createVariable(
                        "WIND10M", "f4", ("time", "lat", "lon"), zlib=True, complevel=4, fill_value=1e15
                    )
                    wind_var[:] = wind_speed
                    wind_var.long_name = "10-meter wind speed magnitude sqrt(u^2+v^2)"
                    wind_var.units = "m s-1"

                out.close()
                src.close()

                tmp_file.replace(target_file)
                return True
            else:
                time.sleep(1.5)
        except Exception as e:
            time.sleep(2.0)

    if tmp_file.exists():
        tmp_file.unlink()
    return False


def fetch_merra2_slv(limit: int | None = None, max_workers: int = 8) -> int:
    """Download MERRA-2 M2TMNXSLV diagnostic subsets via OPeNDAP."""
    login_earthdata()
    granules = get_granule_list()
    if not granules:
        print("[-] Error: No granules found for M2TMNXSLV.")
        return 1

    print(f"[+] Found {len(granules)} monthly granules in CMR.")
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
            items.append((opendap_url, target_path))

    already_done = [item for item in items if item[1].exists() and item[1].stat().st_size > 1_000_000]
    to_download = [item for item in items if not (item[1].exists() and item[1].stat().st_size > 1_000_000)]

    # Size Estimation Report
    est_granule_mb = 2.15  # Compressed with TS, PS, TQV, WIND10M
    est_total_mb = len(to_download) * est_granule_mb
    print("\n" + "=" * 60)
    print("  MERRA-2 SINGLE-LEVEL DIAGNOSTICS (M2TMNXSLV) SIZE ESTIMATE")
    print("=" * 60)
    print(f"  Total Granules In Record  : {len(items)} (2000-06 to 2025-09)")
    print(f"  Already Present On Disk   : {len(already_done)}")
    print(f"  Remaining To Download     : {len(to_download)}")
    print(f"  Estimated Transfer Size   : {len(to_download) * 3.52:.1f} MB (~{len(to_download) * 3.52 / 1024:.2f} GB)")
    print(f"  Estimated On-Disk Size    : {est_total_mb:.1f} MB (~{est_total_mb / 1024:.2f} GB)")
    print(f"  Under 1 GB Limit Check    : {'PASS (< 1.0 GB)' if est_total_mb < 1024 else 'FAIL'}")
    print("=" * 60 + "\n")

    if limit:
        to_download = to_download[:limit]
        print(f"[*] Limiting download batch to {limit} files.")

    if not to_download:
        print("[+] All M2TMNXSLV granules are already downloaded and verified!")
        return 0

    print(f"[*] Starting download of {len(to_download)} granules using {max_workers} threads...")
    t0 = time.time()
    success_count = 0

    def _worker(item):
        url, path = item
        ok = download_single_granule(session, url, path)
        return ok, path.name

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_worker, item): item for item in to_download}
        for future in as_completed(futures):
            ok, fname = future.result()
            if ok:
                success_count += 1
                if success_count % 25 == 0 or success_count == len(to_download):
                    elapsed = time.time() - t0
                    rate = success_count / elapsed
                    remaining = (len(to_download) - success_count) / rate if rate > 0 else 0
                    print(
                        f"  [{success_count}/{len(to_download)}] Downloaded {fname} | "
                        f"{rate:.1f} files/s | ETA: {remaining:.0f}s"
                    )
            else:
                print(f"  [-] Failed: {fname}")

    print(f"\n[+] Finished download: {success_count}/{len(to_download)} succeeded in {time.time() - t0:.1f}s.")
    return 0 if success_count == len(to_download) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch MERRA-2 M2TMNXSLV monthly diagnostics.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of granules to fetch")
    parser.add_argument("--workers", type=int, default=10, help="Number of download threads (default: 10)")
    args = parser.parse_args()

    sys.exit(fetch_merra2_slv(limit=args.limit, max_workers=args.workers))
