"""Access Canvas@SJTU with a saved Playwright session.

Usage:
    python access.py                          # Open Canvas dashboard in visible browser
    python access.py --headless               # Headless mode for data extraction
    python access.py --url /courses/123       # Navigate to specific Canvas page
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SKILL_DIR = Path(__file__).resolve().parent.parent
LOCAL_DIR = SKILL_DIR / "local"
SESSION_FILE = LOCAL_DIR / "oc_session.json"

def main():
    headless = "--headless" in sys.argv
    target_path = "/"

    # Parse --url argument
    for i, arg in enumerate(sys.argv):
        if arg == "--url" and i + 1 < len(sys.argv):
            target_path = sys.argv[i + 1]

    if not SESSION_FILE.exists():
        print(f"ERROR: Session file not found at {SESSION_FILE}")
        print("Run login.py first to create a session.")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(SESSION_FILE))
        page = context.new_page()

        url = f"https://oc.sjtu.edu.cn{target_path}"
        print(f"Navigating to: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        if "login" in page.url.lower():
            print("ERROR: Session expired. Please run login.py again.")
            browser.close()
            sys.exit(2)

        print(f"Connected! URL: {page.url}")
        print(f"Title: {page.title()}")

        if not headless:
            print("Browser window is open. Close it to exit.")
            input("Press Enter to close...")
        else:
            # In headless mode, return page content for further processing
            content = page.content()
            print(f"Page loaded ({len(content)} chars)")

        browser.close()

if __name__ == "__main__":
    main()
