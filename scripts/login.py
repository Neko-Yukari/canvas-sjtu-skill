"""Canvas@SJTU login script - opens browser for manual login, saves session.

Features:
- Signal file detection for manual trigger
- URL change detection (auto-detect login completion)
- All activity logged to oc_login.log
"""
import time, os, sys
from datetime import datetime
from pathlib import Path

# ── Skill-local paths (all runtime data in ../local/) ─────
SKILL_DIR = Path(__file__).resolve().parent.parent
LOCAL_DIR = SKILL_DIR / "local"
SESSION_FILE = LOCAL_DIR / "oc_session.json"
SIGNAL_FILE = LOCAL_DIR / "login_done.txt"
LOG_FILE = LOCAL_DIR / "oc_login.log"

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def main():
    from playwright.sync_api import sync_playwright

    # Cleanup previous signal
    if SIGNAL_FILE.exists():
        SIGNAL_FILE.unlink()

    log("=== Canvas@SJTU Login ===")
    log(f"Session will be saved to: {SESSION_FILE}")

    with sync_playwright() as p:
        log("Launching browser...")
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Step 1: Navigate to Canvas login
        log("Navigating to Canvas login...")
        page.goto("https://oc.sjtu.edu.cn/login/canvas",
                  wait_until="domcontentloaded", timeout=30000)
        log(f"Current URL: {page.url}")

        # Step 2: Guide user
        log("=" * 50)
        log("ACTION REQUIRED: Please log in manually in the browser window.")
        log("  1. Click 'jAccount 登录' on the left side")
        log("  2. Enter username, password, and captcha")
        log("  3. Submit and wait for redirect to Canvas dashboard")
        log(f"  Tell the agent when done. Session → {SESSION_FILE}")
        log("=" * 50)

        # Step 3: Monitor for completion
        saved = False
        for i in range(200):  # ~6.5 min max
            current_url = page.url
            on_login = "login" in current_url.lower() or "jaccount" in current_url.lower()
            signal_exists = SIGNAL_FILE.exists()

            if i % 15 == 0:
                log(f"[{i*2}s] URL: {current_url} | login_page={on_login} | signal={signal_exists}")

            # Trigger: URL left login pages OR signal file detected
            if (not on_login) or signal_exists:
                log("Login completion detected!")
                time.sleep(2)  # Let page stabilize

                try:
                    context.storage_state(path=str(SESSION_FILE))
                    log(f"SUCCESS: Session saved ({SESSION_FILE.stat().st_size} bytes)")
                    saved = True
                except Exception as e:
                    log(f"ERROR saving session: {e}")
                break

            time.sleep(2)

        if not saved:
            log("TIMEOUT: Login not completed within time limit")
            log(f"Final URL: {page.url}")
        else:
            # Cleanup signal file
            if SIGNAL_FILE.exists():
                SIGNAL_FILE.unlink()

        browser.close()
        log("Browser closed.")
        log("=== Done ===")
        return saved

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
