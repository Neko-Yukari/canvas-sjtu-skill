"""Canvas@SJTU unified CLI — API-first with submission support.

Usage:
    python canvas.py dashboard                   Show dashboard (courses + deadlines)
    python canvas.py courses                     List all active courses
    python canvas.py files <course>              List files in a course
    python canvas.py download <course> <kw>      Download files matching keyword
    python canvas.py assignments <course>        List assignments with deadlines
    python canvas.py submit <course> <asgn> <file>  Submit file to assignment (with confirmation)
    python canvas.py token [<token>]             Set or verify Canvas API token (optional, for lightweight mode)
    python canvas.py login                       Re-login (opens browser)
    python canvas.py open                        Open Canvas in visible browser

<course> can be: numeric ID (e.g., 87954) or keyword (e.g., "光纤", "电子线路")
<asgn> can be: assignment name keyword (e.g., "lab5") or numeric ID

Runtime data stored in: ../local/ (gitignored, per-user)
"""
import argparse, sys, time, re, json, os, urllib.parse
from pathlib import Path

# ── Skill-local paths (all runtime data in ../local/) ─────
SKILL_DIR = Path(__file__).resolve().parent.parent
LOCAL_DIR = SKILL_DIR / "local"
SESSION_FILE = LOCAL_DIR / "oc_session.json"
CONFIG_FILE = LOCAL_DIR / "config.json"
DOWNLOAD_DIR = LOCAL_DIR / "downloads"
BASE_URL = "https://oc.sjtu.edu.cn"
API_BASE = f"{BASE_URL}/api/v1"

# ── Config: optional API token (lightweight mode) ─────────

def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def get_token():
    return load_config().get("canvas_token", "")

def save_token(token_str):
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg["canvas_token"] = token_str
    cfg["base_url"] = BASE_URL
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

# ── API helpers ──────────────────────────────────────────

def _api_get(endpoint, params=None):
    """Make authenticated GET request to Canvas API.
    Prefers Bearer token (lightweight), falls back to Playwright session.
    """
    url = endpoint if endpoint.startswith("http") else f"{API_BASE}{endpoint}"
    token = get_token()

    # Lightweight mode: Bearer token
    if token:
        import requests as _r
        resp = _r.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        if resp.status_code == 401:
            print("Token invalid or expired. Run: python canvas.py token <new_token>")
            sys.exit(2)
        if resp.status_code == 200:
            return resp.json()
        return None

    # Heavy mode: Playwright session
    if not SESSION_FILE.exists():
        print(f"ERROR: No session at {SESSION_FILE} and no token configured.")
        print("Run: python canvas.py login")
        sys.exit(1)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        req_ctx = p.request.new_context(storage_state=str(SESSION_FILE))
        resp = req_ctx.get(url, params=params)
        if resp.status == 401:
            print("Session expired. Run: python canvas.py login")
            req_ctx.dispose()
            sys.exit(2)
        if resp.status != 200:
            req_ctx.dispose()
            return None
        data = resp.json()
        req_ctx.dispose()
        return data


def _download_file(file_id, filename, course_name=""):
    """Download a single file by ID. Prefers Bearer token, falls back to session."""
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', filename)
    out_dir = DOWNLOAD_DIR / course_name if course_name else DOWNLOAD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / safe_name
    token = get_token()

    if token:
        import requests as _r
        resp = _r.get(f"{BASE_URL}/files/{file_id}/download?download_frd=1",
                      headers={"Authorization": f"Bearer {token}"},
                      allow_redirects=True)
        if resp.status_code == 200:
            out_path.write_bytes(resp.content)
            size_mb = len(resp.content) / 1024 / 1024
            return out_path, size_mb
        return None, 0

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        req_ctx = p.request.new_context(storage_state=str(SESSION_FILE))
        resp = req_ctx.get(f"{BASE_URL}/files/{file_id}/download?download_frd=1")
        if resp.status == 200:
            out_path.write_bytes(resp.body())
            size_mb = len(resp.body()) / 1024 / 1024
            req_ctx.dispose()
            return out_path, size_mb
        req_ctx.dispose()
        return None, 0


# ── course resolution ────────────────────────────────────

class CourseIndex:
    """In-memory + file-cached course index."""

    def __init__(self):
        self._map = {}          # keyword -> {id, name}
        self._by_id = {}        # id -> name
        self._cache_file = SESSION_FILE.with_name("oc_courses.json")

    def load(self, force=False):
        """Load course index from cache or API."""
        if not force and self._cache_file.exists():
            try:
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                if time.time() - data.get("_ts", 0) < 3600:
                    for k, v in data.items():
                        if k.startswith("_"):
                            continue
                        cid = v["id"] if isinstance(v, dict) else v
                        name = v["name"] if isinstance(v, dict) else k
                        self._by_id[str(cid)] = name
                        self._map[k] = {"id": str(cid), "name": name}
                    return
            except Exception:
                pass

        courses = _api_get("/courses", {"enrollment_state": "active", "per_page": "50"})
        if not courses:
            print("Failed to load courses from API.")
            return

        cache_data = {}
        for c in courses:
            cid = str(c["id"])
            name = c.get("name", cid)
            self._by_id[cid] = name
            self._map[name] = {"id": cid, "name": name}

        # Add prefix-based shortcuts (e.g., "电子" -> "电子线路")
        for name, info in list(self._map.items()):
            for i in range(2, min(len(name), 5)):
                prefix = name[:i]
                if prefix not in self._map:
                    self._map[prefix] = info

        cache_data.update({k: v for k, v in self._map.items()})
        cache_data["_ts"] = time.time()
        self._cache_file.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2),
                                     encoding="utf-8")

        # Rebuild: only add unique short keys
        self._map.clear()
        for name, info in list(self._map.items()):
            self._map[name] = info
        # Re-do from cache
        if self._cache_file.exists():
            try:
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if k.startswith("_"):
                        continue
                    self._map[k] = v if isinstance(v, dict) else {"id": str(v), "name": k}
                    if isinstance(v, dict):
                        self._by_id[str(v["id"])] = v["name"]
                    else:
                        self._by_id[str(v)] = k
            except Exception:
                pass

        # Re-add shortcuts
        base = {k: v for k, v in self._map.items()}
        for name, info in base.items():
            for i in range(2, min(len(name), 5)):
                prefix = name[:i]
                if prefix not in self._map:
                    self._map[prefix] = info

    def resolve(self, query):
        """Resolve course query to ID string."""
        if query.isdigit():
            return query
        ql = query.lower()
        # Exact match
        for name, info in self._map.items():
            if name.lower() == ql:
                return info["id"]
        # Substring match
        matches = []
        for name, info in self._map.items():
            if ql in name.lower():
                matches.append((name, info["id"]))
        if len(matches) == 1:
            return matches[0][1]
        if len(matches) > 1:
            print(f"Multiple matches for '{query}':")
            for name, _ in matches[:10]:
                print(f"  - {name}")
            print("Use a more specific keyword or numeric ID.")
            sys.exit(1)
        print(f"No course found matching '{query}'")
        self.list_all()
        sys.exit(1)

    def get_name(self, cid):
        return self._by_id.get(str(cid), f"Course {cid}")

    def list_all(self):
        seen = set()
        print(f"Active courses:")
        for name, info in self._map.items():
            cid = info["id"]
            if cid not in seen and len(name) > 2:
                seen.add(cid)
                print(f"  [{cid}] {name}")

    def all_courses(self):
        """Return [(id, name)] deduplicated."""
        seen = set()
        result = []
        for name, info in self._map.items():
            cid = info["id"]
            if cid not in seen and len(name) > 2:
                seen.add(cid)
                result.append((cid, name))
        return result


# ── commands ─────────────────────────────────────────────

def cmd_dashboard(index):
    """Show dashboard with courses and upcoming deadlines."""
    courses = _api_get("/courses", {"enrollment_state": "active", "per_page": "50"})
    todos = _api_get("/users/self/todo")

    print("=" * 60)
    print("CANVAS DASHBOARD")
    print("=" * 60)

    if todos:
        print(f"\n--- Upcoming Deadlines ({len(todos)}) ---")
        for item in todos:
            # Todo items from Canvas API
            assignment = item.get("assignment", {})
            context = item.get("context_name", "")
            name = assignment.get("name", item.get("title", "?"))
            due = assignment.get("due_at", "")
            points = assignment.get("points_possible", "?")
            if due:
                try:
                    due_dt = time.strptime(due[:19], "%Y-%m-%dT%H:%M:%S")
                    due_str = time.strftime("%m/%d %H:%M", due_dt)
                except Exception:
                    due_str = due[:16]
            else:
                due_str = "No due date"
            print(f"  [{due_str}] {context}: {name} ({points} pts)")

    if courses:
        print(f"\n--- Active Courses ({len(courses)}) ---")
        for c in courses:
            print(f"  [{c['id']}] {c.get('name', c['id'])}")

    # Also try planner/calendar items
    planner = _api_get("/users/self/planner/items",
                        {"start_date": time.strftime("%Y-%m-%d"),
                         "order": "asc", "per_page": "20"})
    if planner:
        now = time.time()
        print(f"\n--- Upcoming Items ---")
        for item in planner[:10]:
            title = item.get("plannable", {}).get("title", item.get("title", "?"))
            due = item.get("plannable", {}).get("due_at", item.get("plannable_date", ""))
            ctx = item.get("context_name", "")
            due_str = "No due date"
            if due:
                try:
                    due_ts = time.mktime(time.strptime(due[:19], "%Y-%m-%dT%H:%M:%S"))
                    due_str = time.strftime("%m/%d %H:%M", time.localtime(due_ts))
                    remaining = due_ts - now
                    if remaining < 0:
                        due_str += " (OVERDUE!)"
                    elif remaining < 86400:
                        hrs = int(remaining / 3600)
                        due_str += f" ({hrs}h remaining)"
                    else:
                        days = int(remaining / 86400)
                        due_str += f" ({days}d remaining)"
                except Exception:
                    due_str = due[:16]
            print(f"  [{due_str}] {ctx}: {title}")


def cmd_courses(index):
    """List all active courses."""
    index.load(force=True)
    index.list_all()


def cmd_files(index, course_query):
    """List files in a course via API."""
    cid = index.resolve(course_query)
    name = index.get_name(cid)

    # Get file list from API
    files = _api_get(f"/courses/{cid}/files", {"per_page": "200", "sort": "name"})
    if not files:
        print(f"No files found for {name} [{cid}].")
        return

    print(f"Files in {name} [{cid}] ({len(files)} total):")
    for f in files:
        fname = f.get("display_name") or f.get("filename", "?")
        fid = f["id"]
        size = f.get("size", 0)
        size_str = f"{size/1024:.0f}KB" if size < 1024*1024 else f"{size/1024/1024:.1f}MB"
        print(f"  [{fid}] {fname} ({size_str})")


def cmd_download(index, course_query, keyword):
    """Download files matching keyword from a course via API."""
    cid = index.resolve(course_query)
    name = index.get_name(cid)

    files = _api_get(f"/courses/{cid}/files", {"per_page": "200"})
    if not files:
        print(f"No files found for {name} [{cid}].")
        return

    # Find matches
    matches = []
    kw = keyword.lower()
    for f in files:
        fname = f.get("display_name") or f.get("filename", "?")
        if kw in fname.lower():
            matches.append((str(f["id"]), fname))

    if not matches:
        print(f"No files matching '{keyword}' in {name} [{cid}].")
        return

    print(f"Found {len(matches)} matching file(s) in {name}:")
    for fid, fname in matches:
        print(f"  [{fid}] {fname}")

    print(f"\nDownloading to {DOWNLOAD_DIR / name}...")
    for fid, fname in matches:
        print(f"  {fname} ...", end=" ", flush=True)
        path, size_mb = _download_file(fid, fname, name)
        if path:
            print(f"OK ({size_mb:.1f}MB)")
            print(f"    -> {path}")
        else:
            print("FAILED")

    print("Done.")


def cmd_assignments(index, course_query):
    """List assignments for a course via API."""
    cid = index.resolve(course_query)
    name = index.get_name(cid)

    assignments = _api_get(f"/courses/{cid}/assignments",
                           {"per_page": "50", "order_by": "due_at"})
    if not assignments:
        print(f"No assignments found for {name} [{cid}].")
        return

    # Also get submissions to know status
    submissions = _api_get(f"/courses/{cid}/students/submissions",
                           {"student_ids[]": "all", "per_page": "50"})
    sub_map = {}
    if submissions:
        for s in submissions:
            aid = s.get("assignment_id")
            if aid:
                sub_map[aid] = s

    now = time.time()
    print(f"Assignments for {name} [{cid}] ({len(assignments)} total):")
    print("-" * 80)

    for a in assignments:
        a_id = a["id"]
        a_name = a.get("name", f"Assignment {a_id}")
        due = a.get("due_at", "")
        points = a.get("points_possible", 0)
        status = "open"

        if due:
            try:
                due_ts = time.mktime(time.strptime(due[:19], "%Y-%m-%dT%H:%M:%S"))
                due_str = time.strftime("%m/%d %H:%M", time.localtime(due_ts))
                if due_ts < now:
                    status = "CLOSED"
                    due_str += " (CLOSED)"
                else:
                    remaining = due_ts - now
                    if remaining < 86400:
                        hrs = int(remaining / 3600)
                        due_str += f" ({hrs}h left)"
                    else:
                        days = int(remaining / 86400)
                        due_str += f" ({days}d left)"
            except Exception:
                due_str = due[:16]
        else:
            due_str = "No due date"

        # Submission status
        sub = sub_map.get(a_id, {})
        submitted = sub.get("workflow_state", "unsubmitted")
        score = sub.get("score", None)
        sub_status = ""
        if submitted == "submitted":
            sub_status = "[SUBMITTED]"
        elif submitted == "graded":
            sub_status = f"[GRADED: {score}/{points}]" if score is not None else "[GRADED]"
        elif status == "open":
            sub_status = "[NOT SUBMITTED]"

        print(f"  [{status}] {a_name}")
        print(f"      Due: {due_str} | Points: {points}")
        if sub_status:
            print(f"      Status: {sub_status}")
        if a.get("description"):
            desc = re.sub(r'<[^>]+>', '', a["description"] or "").strip()[:150]
            if desc:
                print(f"      {desc}")
        print()


def cmd_submit(index, course_query, assignment_query, file_path):
    """Submit a file to a Canvas assignment with explicit user confirmation."""
    # ── Resolve course and assignment ──
    cid = index.resolve(course_query)
    name = index.get_name(cid)

    file_p = Path(file_path)
    if not file_p.exists():
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)
    file_size = file_p.stat().st_size
    content_type = _guess_mime(file_p)

    assignments = _api_get(f"/courses/{cid}/assignments", {"per_page": "50"})
    if not assignments:
        print(f"No assignments found for {name} [{cid}].")
        sys.exit(1)

    # Match assignment by keyword or numeric ID
    aq = assignment_query.lower()
    matches = []
    for a in assignments:
        a_name = a.get("name", "")
        if aq in a_name.lower() or str(a["id"]) == assignment_query:
            matches.append(a)

    if len(matches) == 0:
        print(f"No assignment matching '{assignment_query}' in {name} [{cid}].")
        print("Available assignments:")
        for a in assignments[:15]:
            print(f"  [{a['id']}] {a.get('name', a['id'])}")
        sys.exit(1)
    if len(matches) > 1:
        print(f"Multiple assignments match '{assignment_query}':")
        for a in matches:
            print(f"  [{a['id']}] {a.get('name', a['id'])}")
        print("Use a more specific keyword or numeric ID.")
        sys.exit(1)

    assign = matches[0]
    a_id = assign["id"]
    a_name = assign.get("name", f"Assignment {a_id}")
    sub_types = assign.get("submission_types", [])
    due = assign.get("due_at", "")
    points = assign.get("points_possible", 0)

    # Validate submission type
    if "online_upload" not in sub_types:
        print(f"ERROR: Assignment '{a_name}' does not accept file uploads.")
        print(f"  Submission types: {sub_types}")
        sys.exit(1)

    # Show preview
    print("=" * 60)
    print("SUBMISSION PREVIEW")
    print("=" * 60)
    print(f"  Course:     {name} [{cid}]")
    print(f"  Assignment: {a_name} [{a_id}]")
    print(f"  Due:        {due[:16] if due else 'No due date'}")
    print(f"  Points:     {points}")
    print(f"  File:       {file_p}")
    print(f"  Size:       {file_size:,} bytes ({file_size/1024:.1f} KB)")
    print(f"  Type:       {content_type}")

    # ── Confirmation ──
    print("\n" + "!" * 60)
    print(f"  WARNING: This will SUBMIT your file to '{a_name}'.")
    print(f"  This action CANNOT be undone (unless multiple attempts allowed).")
    print("!" * 60)
    resp = input("\nType 'SUBMIT' to confirm: ")
    if resp.strip() != "SUBMIT":
        print("Aborted. Nothing was submitted.")
        sys.exit(0)

    # ── Step 1: Upload preflight ──
    print("\n[1/3] Requesting upload preflight...")
    token = get_token()

    if token:
        _submit_with_token(cid, a_id, a_name, file_p, file_size, content_type, token)
    else:
        _submit_with_session(cid, a_id, a_name, file_p, file_size, content_type)

    # Verify submission
    sub = _api_get(f"/courses/{cid}/assignments/{a_id}/submissions/self")
    if sub:
        st = sub.get("workflow_state", "?")
        print(f"\n  Final status: {st}")
        if st in ("submitted", "graded"):
            at = sub.get("submitted_at", "")
            print(f"  Submitted at: {at[:19] if at else 'N/A'}")

    print("\n" + "=" * 60)
    print("SUBMISSION COMPLETE")
    print("=" * 60)


def _submit_with_token(cid, a_id, a_name, file_p, file_size, content_type, token):
    """Submit using Bearer token (lightweight, no Playwright needed)."""
    import requests as _r
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    body = f"name={urllib.parse.quote(file_p.name)}&size={file_size}&content_type={urllib.parse.quote(content_type)}"
    r = _r.post(f"{API_BASE}/courses/{cid}/assignments/{a_id}/submissions/self/files",
                headers=h, data=body)
    if r.status_code != 200:
        print(f"ERROR: Upload preflight failed (HTTP {r.status_code})")
        print(r.text[:500])
        sys.exit(1)

    ud = r.json()
    upload_url = ud["upload_url"]
    upload_params = ud["upload_params"]
    print(f"  Upload URL obtained: {upload_url[:60]}...")

    print(f"[2/3] Uploading file to cloud storage...")
    with open(file_p, "rb") as fh:
        s3_resp = _r.post(upload_url, data=upload_params, files={"file": (file_p.name, fh, content_type)})
    if s3_resp.status_code not in (200, 201, 204, 303):
        print(f"ERROR: S3 upload failed (HTTP {s3_resp.status_code})")
        print(s3_resp.text[:500])
        sys.exit(1)
    print(f"  File uploaded successfully (HTTP {s3_resp.status_code}).")

    key = upload_params.get("key", "")
    attach_match = re.search(r"attachments/(\d+)/", key)
    if not attach_match:
        print("WARNING: Could not determine attachment ID.")
        print(f"Key: {key}")
        sys.exit(0)

    attach_id = attach_match.group(1)
    print(f"[3/3] Confirming submission (attachment {attach_id})...")
    confirm_data = f"submission[submission_type]=online_upload&submission[file_ids][]={attach_id}"
    cr = _r.post(f"{API_BASE}/courses/{cid}/assignments/{a_id}/submissions",
                 headers=h, data=confirm_data)
    print(f"  Submission confirm: HTTP {cr.status_code}")
    if cr.status_code in (200, 201):
        try:
            result = cr.json()
            print(f"  Status: {result.get('workflow_state', '?')}")
        except Exception:
            pass


def _submit_with_session(cid, a_id, a_name, file_p, file_size, content_type):
    """Submit using Playwright session (for when no token is configured)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        req = p.request.new_context(storage_state=str(SESSION_FILE))

        state = req.storage_state()
        csrf = None
        for c in state.get("cookies", []):
            if c["name"] == "_csrf_token":
                csrf = urllib.parse.unquote(c["value"])
        if not csrf:
            print("ERROR: Could not extract CSRF token from session.")
            req.dispose()
            sys.exit(1)

        headers = {
            "X-CSRF-Token": csrf,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        params = f"name={urllib.parse.quote(file_p.name)}&size={file_size}&content_type={urllib.parse.quote(content_type)}"
        resp = req.post(f"{API_BASE}/courses/{cid}/assignments/{a_id}/submissions/self/files",
                        headers=headers, data=params)
        if resp.status != 200:
            print(f"ERROR: Upload preflight failed (HTTP {resp.status})")
            print(resp.text()[:500])
            req.dispose()
            sys.exit(1)

        upload_data = resp.json()
        upload_url = upload_data["upload_url"]
        upload_params = upload_data["upload_params"]
        print(f"  Upload URL obtained: {upload_url[:60]}...")

        print(f"[2/3] Uploading file to cloud storage...")
        with open(file_p, "rb") as fh:
            file_bytes = fh.read()
        multipart = {k: v for k, v in upload_params.items()}
        multipart["file"] = {"name": file_p.name, "mimeType": content_type, "buffer": file_bytes}
        s3_resp = req.post(upload_url, multipart=multipart)
        if s3_resp.status not in (200, 201, 204, 303):
            print(f"ERROR: S3 upload failed (HTTP {s3_resp.status})")
            print(s3_resp.text()[:500])
            req.dispose()
            sys.exit(1)
        print(f"  File uploaded successfully (HTTP {s3_resp.status}).")

        key = upload_params.get("key", "")
        attach_match = re.search(r"attachments/(\d+)/", key)
        if not attach_match:
            print("WARNING: Could not determine attachment ID.")
            print(f"Key: {key}")
            req.dispose()
            sys.exit(0)

        attach_id = attach_match.group(1)
        print(f"[3/3] Confirming submission (attachment {attach_id})...")
        confirm_data = f"submission[submission_type]=online_upload&submission[file_ids][]={attach_id}"
        confirm_resp = req.post(f"{API_BASE}/courses/{cid}/assignments/{a_id}/submissions",
                                headers=headers, data=confirm_data)
        print(f"  Submission confirm: HTTP {confirm_resp.status}")
        if confirm_resp.status in (200, 201):
            try:
                result = confirm_resp.json()
                print(f"  Status: {result.get('workflow_state', '?')}")
            except Exception:
                pass
        req.dispose()


def _guess_mime(file_path):
    """Guess MIME type from file extension."""
    ext = file_path.suffix.lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".py": "text/plain",
        ".c": "text/plain",
        ".cpp": "text/plain",
        ".h": "text/plain",
        ".zip": "application/zip",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".html": "text/html",
        ".md": "text/markdown",
        ".json": "application/json",
        ".mp4": "video/mp4",
        ".mp3": "audio/mpeg",
    }
    return mime_map.get(ext, "application/octet-stream")


def cmd_open():
    """Open Canvas in visible browser with saved session."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=str(SESSION_FILE))
        page = ctx.new_page()
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        print(f"Connected: {page.url}")
        print("Browser window is open. Press Enter here to close...")
        input()
        browser.close()


def cmd_token(args):
    """Set or verify Canvas API token."""
    if args.token:
        save_token(args.token.strip())
        print("Token saved to local/config.json")
        # Verify
        import requests as _r
        r = _r.get(f"{API_BASE}/users/self",
                   headers={"Authorization": f"Bearer {args.token.strip()}"})
        if r.status_code == 200:
            data = r.json()
            print(f"Token valid — logged in as: {data.get('name', '?')} (ID: {data.get('id', '?')})")
        else:
            print(f"WARNING: Token returned HTTP {r.status_code}. Check validity.")
    else:
        token = get_token()
        if token:
            print(f"Token configured (masked): {token[:8]}...{token[-4:]}")
            import requests as _r
            r = _r.get(f"{API_BASE}/users/self",
                       headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200:
                data = r.json()
                print(f"Status: valid — {data.get('name', '?')} (ID: {data.get('id', '?')})")
                print(f"Lightweight mode: active (API calls use requests, no Playwright overhead)")
            else:
                print(f"Status: INVALID (HTTP {r.status_code})")
        else:
            print("No token configured. Running in Playwright session mode.")
            print("To add a token: python canvas.py token <your_canvas_api_token>")
            print("Get a token from: Canvas → Settings → Approved Integrations → New Access Token")


def cmd_login():
    """Run manual login script."""
    import subprocess
    login_script = Path(__file__).resolve().parent / "login.py"
    subprocess.run([sys.executable, str(login_script)], check=True)


# ── main ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Canvas@SJTU CLI (READ-ONLY, API-first)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("dashboard", help="Show dashboard with courses and deadlines")
    sub.add_parser("courses", help="List all active courses (force-refresh from API)")
    p_files = sub.add_parser("files", help="List files in a course")
    p_files.add_argument("course", help="Course ID or keyword")
    p_dl = sub.add_parser("download", help="Download files matching keyword")
    p_dl.add_argument("course", help="Course ID or keyword")
    p_dl.add_argument("keyword", help="Keyword to match file names")
    p_asgn = sub.add_parser("assignments", help="List assignments for a course")
    p_asgn.add_argument("course", help="Course ID or keyword")
    p_submit = sub.add_parser("submit", help="Submit a file to an assignment (with confirmation)")
    p_submit.add_argument("course", help="Course ID or keyword")
    p_submit.add_argument("assignment", help="Assignment keyword or numeric ID")
    p_submit.add_argument("file", help="Path to file to submit")
    sub.add_parser("open", help="Open Canvas in visible browser")
    sub.add_parser("login", help="Manual re-login (opens browser)")
    p_token = sub.add_parser("token", help="Set or verify Canvas API token (enables lightweight mode)")
    p_token.add_argument("token", nargs="?", help="Your Canvas API token (leave empty to check status)")

    args = parser.parse_args()

    index = None
    if args.command in ("dashboard", "courses", "files", "download", "assignments", "submit"):
        index = CourseIndex()
        index.load()

    if args.command == "dashboard":
        cmd_dashboard(index)
    elif args.command == "courses":
        cmd_courses(index)
    elif args.command == "files":
        cmd_files(index, args.course)
    elif args.command == "download":
        cmd_download(index, args.course, args.keyword)
    elif args.command == "assignments":
        cmd_assignments(index, args.course)
    elif args.command == "submit":
        cmd_submit(index, args.course, args.assignment, args.file)
    elif args.command == "open":
        cmd_open()
    elif args.command == "login":
        cmd_login()
    elif args.command == "token":
        cmd_token(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
