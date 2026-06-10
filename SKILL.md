---
name: canvas-sjtu
description: Login, session management, and file operations for Canvas@SJTU (oc.sjtu.edu.cn) via jAccount SSO. Use when the user needs to access Canvas@SJTU, login to oc.sjtu.edu.cn, list courses/assignments, download files, submit assignments, or extract data from Canvas. Handles jAccount captcha login, Playwright-based session persistence, Canvas REST API, and S3 file uploads. Provides a unified CLI (canvas.py) for all operations.
---
name: canvas-sjtu
description: Login, session management, and file operations for Canvas@SJTU (oc.sjtu.edu.cn) via jAccount SSO. Use when the user needs to access Canvas@SJTU, login to oc.sjtu.edu.cn, list courses/assignments, download files, submit assignments, or extract data from Canvas. Handles jAccount captcha login, Playwright-based session persistence, Canvas REST API, and S3 file uploads. Provides a unified CLI (canvas.py) for all operations.
---

# Canvas@SJTU Session Manager

## Setup (First Time)

```bash
# 1. Install Playwright
pip install playwright
playwright install chromium

# 2. Create local data directory
mkdir -p local

# 3. Login (opens browser for manual login)
python scripts/login.py
```

All runtime data stored in `./local/` (gitignored):
- `local/oc_session.json` — Playwright session state
- `local/oc_courses.json` — Course index cache
- `local/downloads/` — Downloaded files
- `local/oc_login.log` — Login activity log

## Quick Start

```bash
# Unified CLI (recommended)
python scripts/canvas.py <command>
```

| Command | Function | Safety |
|---------|----------|--------|
| `dashboard` | Home overview (active courses + upcoming deadlines) | Read-only |
| `courses` | List all active courses (force-refresh from API) | Read-only |
| `files <course>` | List all files in a course | Read-only |
| `download <course> <kw>` | Download files matching keyword | Read-only |
| `assignments <course>` | List assignments (due dates, scores, submission status) | Read-only |
| `submit <course> <asgn> <file>` | Submit file to assignment via S3 upload | Requires explicit confirmation |
| `open` | Open Canvas in visible browser | Read-only |
| `login` | Manual re-login (opens browser) | Write (session) |

`<course>` accepts: numeric ID (e.g., `87954`) or keyword (e.g., `光纤`, `电子线路`).

## Login Flow

1. Canvas login page: `https://oc.sjtu.edu.cn/login/canvas`
2. jAccount SSO link: `/login/openid_connect` → redirects to `jaccount.sjtu.edu.cn/jaccount/jalogin`
3. jAccount form fields: `#input-login-user`, `#input-login-pass`, `#input-login-captcha`
4. Captcha URL: `captcha?uuid=UUID&t=TIMESTAMP` (110x40px, 4-5 lowercase letters)
5. After SSO, redirect back to Canvas dashboard

## Submission API (Write — with confirmation)

The `submit` command implements the 3-step Canvas file upload pipeline:

1. **Upload preflight**: `POST /api/v1/courses/:cid/assignments/:aid/submissions/self/files`
   - Body: `name=X&size=N&content_type=Y`
   - Returns: `{upload_url, upload_params}` (AWS S3 presigned URL)

2. **S3 upload**: `POST {upload_url}` with multipart form data
   - Includes all `upload_params` + `file` binary
   - Uses Playwright API request context (bypasses CORS, shares session cookies)

3. **Confirm submission**: `POST /api/v1/courses/:cid/assignments/:aid/submissions`
   - Body: `submission[submission_type]=online_upload&submission[file_ids][]=:id`
   - Requires `X-CSRF-Token` header (extracted from session cookies, URL-decoded)

**Safety**: User must type `SUBMIT` explicitly to confirm. Preview shows course, assignment, file path, size, and MIME type before confirmation.

## Architecture

- **API-first**: Uses Canvas REST API (`/api/v1`) instead of HTML scraping
- **Playwright request context**: `p.request.new_context(storage_state=...)` to share session cookies for file downloads and uploads (avoids CORS issues with page-level `fetch()`)
- **CourseIndex**: 1-hour file cache (`oc_courses.json`) with keyword + numeric ID resolution
- **Session**: Playwright `storage_state()` JSON → cookies + localStorage → restored via `new_context(storage_state=...)`

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/canvas.py` | **Unified CLI** (all operations) |
| `scripts/login.py` | Manual login with browser window, saves session |
| `scripts/access.py` | Legacy: open Canvas with saved session |

## Platform Notes

- **Windows**: Use `Start-Process` (not `-NoNewWindow`) for background browser scripts
- **enhanced_terminal**: Avoid for Python on Windows (DLL init error -1073741502)
- **Chrome profile**: `C:\Users\81004\AppData\Local\Google\Chrome\User Data\Default`
