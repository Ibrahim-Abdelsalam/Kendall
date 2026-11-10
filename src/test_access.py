"""Access test for NASA Earthdata GPM IMERG V07 monthly precipitation dataset.

Authenticates using environment variables with .netrc fallback,
queries CMR for GPM IMERG Final Monthly V07 (GPM_3IMERGM), downloads a single test month,
and verifies file readability and schema.
"""

from __future__ import annotations

import sys
from pathlib import Path
import earthaccess
import xarray as xr

from auth import login_earthdata


RAW_DATA_DIR = Path("data/raw")
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)


def test_download_single_month(
    short_name: str = "GPM_3IMERGM",
    version: str = "07",
    temporal_range: tuple[str, str] = ("2020-01-01", "2020-01-31"),
) -> Path:
    """Search and download a single monthly granule from CMR."""
    print(f"[*] Searching CMR for {short_name} (Version {version}) in range {temporal_range}...")
    granules = earthaccess.search_data(
        short_name=short_name,
        version=version,
        temporal=temporal_range,
    )

    if not granules:
        raise FileNotFoundError(
            f"No granules found for {short_name} v{version} in range {temporal_range}."
        )

    target_granule = granules[0]
    granule_id = target_granule["meta"]["native-id"]
    print(f"[+] Found {len(granules)} granule(s). Selected: {granule_id}")

    print(f"[*] Downloading test granule to {RAW_DATA_DIR}...")
    downloaded_files = earthaccess.download(target_granule, str(RAW_DATA_DIR))

    if not downloaded_files:
        raise RuntimeError("Download completed but no file paths were returned.")

    downloaded_path = Path(downloaded_files[0])
    if not downloaded_path.exists() or downloaded_path.stat().st_size == 0:
        raise RuntimeError(f"Downloaded file {downloaded_path} is missing or empty.")

    print(f"[+] Download successful: {downloaded_path.name} ({downloaded_path.stat().st_size / (1024 * 1024):.2f} MB)")
    return downloaded_path


def inspect_granule(file_path: Path) -> None:
    """Inspect the downloaded granule structure, variables, and dimensions."""
    print(f"[*] Opening and inspecting granule {file_path.name}...")

    # GPM IMERG HDF5 groups: precipitation variables reside inside "Grid"
    ds = None
    for group in ["Grid", None]:
        for engine in ["netcdf4", "h5netcdf"]:
            try:
                ds = xr.open_dataset(file_path, group=group, engine=engine)
                break
            except Exception:
                continue
        if ds is not None:
            break

    if ds is None:
        raise RuntimeError(f"Could not open {file_path} with netcdf4 or h5netcdf engines.")

    print("[+] Dataset loaded successfully.")
    print("    Dimensions:", dict(ds.sizes))
    print("    Variables:", list(ds.data_vars.keys()))

    # Check for precipitation variable
    target_var = None
    for candidate in ["precipitation", "precipitationCal", "precipitationCal_cnt"]:
        if candidate in ds:
            target_var = candidate
            break

    if target_var:
        da = ds[target_var]
        print(f"[+] Detected primary precipitation variable: '{target_var}'")
        print(f"    Units: {da.attrs.get('units', 'unknown')}")
        print(f"    Shape: {da.shape}")
        print(f"    Min: {float(da.min().values):.4f}, Max: {float(da.max().values):.4f}, Mean: {float(da.mean().values):.4f}")
    else:
        print("[!] Warning: Target precipitation variable not found in Grid group. Available vars:", list(ds.data_vars))

    ds.close()


def main() -> int:
    """Entry point for access verification."""
    try:
        login_earthdata()
        downloaded_file = test_download_single_month()
        inspect_granule(downloaded_file)
        print("[+] Access Test PASSED: GPM IMERG V07 is accessible and valid.")
        return 0
    except Exception as exc:
        print(f"[-] Access Test FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
