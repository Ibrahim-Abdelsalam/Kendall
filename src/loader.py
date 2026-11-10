"""Terminal loading screen that automatically erases/deletes itself upon completion.

Can be used as a context manager for any long-running Earth-science pipeline task:

    with TerminalLoadingScreen("Downloading GPM IMERG granules..."):
        # run task
    # Screen is erased completely upon exit!
"""

from __future__ import annotations

import itertools
import sys
import threading
import time


class TerminalLoadingScreen:
    """Animated in-terminal loading indicator that erases itself upon exit."""

    def __init__(self, message: str = "Processing...", delay: float = 0.08):
        self.message = message
        self.delay = delay
        self.spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _spin(self) -> None:
        while not self._stop_event.is_set():
            char = next(self.spinner)
            # \r carriage return + ANSI clear line sequence (\033[K)
            sys.stdout.write(f"\r\033[K\033[36m{char}\033[0m {self.message}")
            sys.stdout.flush()
            time.sleep(self.delay)

    def __enter__(self) -> "TerminalLoadingScreen":
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def update_message(self, new_message: str) -> None:
        """Update status message dynamically."""
        self.message = new_message

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        # Erase line completely from the terminal buffer
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


if __name__ == "__main__":
    print("[*] Testing self-deleting terminal loading screen...")
    with TerminalLoadingScreen("Fetching satellite granules (will delete itself in 3s)...") as screen:
        time.sleep(1.5)
        screen.update_message("Applying 2.5° regridding (almost done)...")
        time.sleep(1.5)
    print("[+] Loading screen finished and completely erased from terminal!")
