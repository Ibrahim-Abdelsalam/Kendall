"""Earthdata authentication module.

Implements sequential login strategy:
1. Check environment variables (or local .env file if present).
2. earthaccess.login(strategy="environment")
3. Fallback to earthaccess.login(strategy="netrc") if environment variables are missing or fail.
Never prints or logs credentials.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import earthaccess


def load_local_env_file() -> None:
    """Load credentials from local .env if present in workspace root."""
    env_path = Path(".env")
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD", "EARTHDATA_TOKEN"):
                            os.environ[key] = val
        except Exception:
            pass


def login_earthdata() -> earthaccess.Auth:
    """Authenticate with NASA Earthdata Login.

    Tries environment strategy first; falls back to ~/.netrc.
    Never exposes or prints credentials.
    """
    load_local_env_file()

    has_env_creds = bool(os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")) or bool(os.environ.get("EARTHDATA_TOKEN"))

    if has_env_creds:
        try:
            print("[*] Attempting Earthdata login via environment strategy...")
            auth = earthaccess.login(strategy="environment")
            if auth and getattr(auth, "authenticated", False):
                print("[+] Successfully authenticated via environment variables.")
                return auth
        except Exception as exc:
            print(f"[!] Environment login failed: {exc}. Trying .netrc fallback...", file=sys.stderr)
    else:
        print("[*] Environment credentials not set. Falling back to .netrc strategy...")

    try:
        auth = earthaccess.login(strategy="netrc")
        if auth and getattr(auth, "authenticated", False):
            print("[+] Successfully authenticated via ~/.netrc.")
            return auth
        raise PermissionError("Failed to authenticate using ~/.netrc.")
    except Exception as exc:
        raise PermissionError(
            "Earthdata authentication failed. Please provide credentials via "
            "EARTHDATA_USERNAME and EARTHDATA_PASSWORD environment variables, a local .env file, or ~/.netrc."
        ) from exc
