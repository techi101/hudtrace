"""Screenshot the demo at 1440px and 390px and check for console errors / horizontal overflow.

    python site/check_page.py <url> [out_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main(url: str, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--mute-audio"])
        for width, height in ((1440, 1000), (390, 844)):
            page = browser.new_page(viewport={"width": width, "height": height})
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url, wait_until="networkidle")
            page.wait_for_selector(".step")
            sw = page.evaluate("document.documentElement.scrollWidth")
            page.screenshot(path=str(out / f"screenshot_{width}.png"), full_page=width != 1440)
            # click path: open the loop, click a step, check the drawer shows it
            page.click(".jump")
            page.wait_for_timeout(400)
            drawer_ok = "First failing step" in page.inner_text("#drawer-body")
            sw2 = page.evaluate("document.documentElement.scrollWidth")
            ok = not errors and sw <= width and sw2 <= width and drawer_ok
            bad += not ok
            print(f"{width}px: scrollWidth={sw}/{sw2} console_errors={errors} drawer_ok={drawer_ok} -> {'OK' if ok else 'FAIL'}")
            if width == 390:
                page.screenshot(path=str(out / "screenshot_390_drawer.png"))
            page.close()
        browser.close()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2] if len(sys.argv) > 2 else "docs")))
