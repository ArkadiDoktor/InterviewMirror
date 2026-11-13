"""Open the app in a real (headless) browser: wakes it from sleep and checks it works.

A plain HTTP request does not wake a Streamlit Community Cloud app - only a real
browser session does. This script:
  * clicks "Yes, get this app back up!" if the app is asleep,
  * waits until the setup screen has actually rendered,
  * exits with an error if it never does, so GitHub Actions marks the run red
    and emails the repository owner.

    pip install playwright==1.63.0 && playwright install chromium
    python tools/keep_awake.py https://your-app.streamlit.app [more urls...]
"""
from __future__ import annotations

import os
import re
import sys
import time

from playwright.sync_api import Page, sync_playwright

READY_TEXT = "התחלת הראיון"                     # the start button on the setup screen
WAKE_BUTTON = re.compile(r"get this app back up", re.I)
TIMEOUT = 240


def _frames(page: Page):
    return [page.main_frame] + [f for f in page.frames if f is not page.main_frame]


def check(page: Page, url: str) -> tuple[bool, str, float]:
    t0 = time.time()
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    woke = False
    while time.time() - t0 < TIMEOUT:
        for frame in _frames(page):
            try:
                if frame.get_by_text(READY_TEXT).count():
                    return True, "woken up" if woke else "awake", time.time() - t0
                wake = frame.get_by_role("button", name=WAKE_BUTTON)
                if not woke and wake.count():
                    wake.first.click()
                    woke = True
            except Exception:  # noqa: BLE001 - frames come and go while the app boots
                pass
        time.sleep(2)
    return False, "did not become ready", time.time() - t0


def main(urls: list[str]) -> int:
    failures = 0
    lines = ["| App | Status | Seconds |", "|---|---|---|"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for url in urls:
            page = browser.new_page()
            try:
                ok, status, secs = check(page, url)
            except Exception as exc:  # noqa: BLE001
                ok, status, secs = False, f"error: {type(exc).__name__}", 0.0
            failures += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {url}: {status} ({secs:.0f}s)")
            lines.append(f"| {url} | {'✅' if ok else '❌'} {status} | {secs:.0f} |")
            page.close()
        browser.close()
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    targets = [u.strip() for u in (sys.argv[1:] or os.environ.get("APP_URLS", "").split(",")) if u.strip()]
    if not targets:
        sys.exit("Give the app URL(s) as arguments or in APP_URLS.")
    sys.exit(main(targets))
