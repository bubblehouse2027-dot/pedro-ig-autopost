#!/usr/bin/env python3
"""Publish due Instagram posts from posts.csv via the official Instagram API.

Modes
  python publish.py              publish every pending post whose time has come
  python publish.py --check      check token, account, media links; changes nothing
  python publish.py --dry-run P03
                                 build P03 on Instagram's side and wait until it is ready,
                                 but do NOT publish it (the draft expires by itself in 24 h)

Environment
  IG_ACCESS_TOKEN   access token (GitHub secret). Never printed.
                    With IG_USER_ID set: a Facebook Page token (never expires), used on graph.facebook.com.
                    Without IG_USER_ID: an Instagram Login token (expires after 60 days), used on graph.instagram.com.
  IG_USER_ID        Instagram business account id, e.g. 17841400786098098 (GitHub secret)
  PAGES_BASE_URL    e.g. https://yourname.github.io/pedro-ig-autopost  (no trailing slash)
  MAX_LATE_HOURS    optional, default 24: posts later than this are marked "missed", not posted
"""
import csv, glob, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
API = "https://graph.facebook.com/v26.0" if IG_USER_ID else "https://graph.instagram.com"
TZ = ZoneInfo("Europe/Lisbon")
HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "posts.csv")
FIELDS = ["id", "date", "time", "type", "media", "thumb_offset_ms", "status", "instagram_id"]

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
BASE = os.environ.get("PAGES_BASE_URL", "").strip().rstrip("/")
MAX_LATE = timedelta(hours=float(os.environ.get("MAX_LATE_HOURS", "24")))


class ApiError(Exception):
    pass


def call(method, path, params=None):
    params = dict(params or {})
    params["access_token"] = TOKEN
    data = urllib.parse.urlencode(params)
    if method == "GET":
        req = urllib.request.Request(f"{API}/{path}?{data}")
    else:
        req = urllib.request.Request(f"{API}/{path}", data=data.encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(body).get("error", {})
            msg = f"{err.get('message')} (code {err.get('code')}, subcode {err.get('error_subcode')})"
        except ValueError:
            msg = body[:300]
        raise ApiError(f"{method} {path.split('?')[0]} failed: HTTP {e.code}: {msg}") from None


def load():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(rows):
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def due_utc(row):
    local = datetime.strptime(f"{row['date']} {row['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    return local.astimezone(timezone.utc)


def media_files(row):
    # Media may sit in media/ or directly in the repository's top folder.
    pattern = row["media"].strip()
    files = sorted(os.path.relpath(p, HERE) for p in glob.glob(os.path.join(HERE, "media", pattern)))
    if not files:
        files = sorted(os.path.relpath(p, HERE) for p in glob.glob(os.path.join(HERE, pattern)))
    if not files:
        raise ApiError(f"{row['id']}: no file matches '{pattern}' (looked in media/ and the top folder)")
    if row["type"] == "reel" and len(files) != 1:
        raise ApiError(f"{row['id']}: a reel needs exactly one video, found {files}")
    if row["type"] == "carousel":
        if not 2 <= len(files) <= 10:
            raise ApiError(f"{row['id']}: a carousel needs 2-10 images, found {len(files)}")
        bad = [f for f in files if not f.lower().endswith((".jpg", ".jpeg"))]
        if bad:
            raise ApiError(f"{row['id']}: Instagram API accepts JPEG only, convert {bad}")
    return files


def url_for(relpath):
    return f"{BASE}/{urllib.parse.quote(relpath.replace(os.sep, '/'))}"


def check_url(url):
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, ""


def caption(row):
    with open(os.path.join(HERE, "captions", f"{row['id']}.txt"), encoding="utf-8") as f:
        text = f.read().rstrip("\n")
    if len(text) > 2200 or text.count("#") > 30:
        raise ApiError(f"{row['id']}: caption over 2,200 characters or 30 hashtags")
    return text


def wait_ready(container_id, label):
    # Meta suggests polling about once a minute for up to 5 minutes; we poll every 20 s for up to 6 min.
    for _ in range(18):
        st = call("GET", container_id, {"fields": "status_code,status"})
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise ApiError(f"{label}: Instagram could not process the media: {st.get('status')}")
        time.sleep(20)
    raise ApiError(f"{label}: still processing after 6 minutes; will retry next run")


def build(ig_id, row):
    files = media_files(row)
    text = caption(row)
    if row["type"] == "reel":
        params = {"media_type": "REELS", "video_url": url_for(files[0]), "caption": text,
                  "share_to_feed": "true", "thumb_offset": row.get("thumb_offset_ms") or "0"}
        cid = call("POST", f"{ig_id}/media", params)["id"]
        wait_ready(cid, row["id"])
        return cid
    children = []
    for name in files:
        cid = call("POST", f"{ig_id}/media", {"image_url": url_for(name), "is_carousel_item": "true"})["id"]
        wait_ready(cid, f"{row['id']}/{name}")
        children.append(cid)
    cid = call("POST", f"{ig_id}/media", {"media_type": "CAROUSEL", "children": ",".join(children),
                                          "caption": text})["id"]
    wait_ready(cid, row["id"])
    return cid


def account():
    if IG_USER_ID:  # Facebook Login: Page token + Instagram business account id
        me = call("GET", IG_USER_ID, {"fields": "id,username"})
        me["account_type"] = "BUSINESS"
        return IG_USER_ID, me
    me = call("GET", "me", {"fields": "user_id,username,account_type"})
    return me["user_id"], me


def main():
    if not TOKEN:
        sys.exit("IG_ACCESS_TOKEN is missing (add it as a GitHub secret).")
    if not BASE.startswith("https://"):
        sys.exit("PAGES_BASE_URL is missing or not https (add it as a GitHub variable).")
    args = sys.argv[1:]
    rows = load()
    ig_id, me = account()
    print(f"Account: @{me.get('username')} ({me.get('account_type')})")

    if args[:1] == ["--check"]:
        lim = call("GET", f"{ig_id}/content_publishing_limit", {"fields": "quota_usage,config"})
        print("Publishing limit:", json.dumps(lim.get("data", lim)))
        problems = 0
        for row in rows:
            try:
                files = media_files(row)
                caption(row)
            except ApiError as e:
                print("PROBLEM", e); problems += 1; continue
            for name in files:
                status, ctype = check_url(url_for(name))
                if status != 200:
                    print(f"PROBLEM {row['id']}: {url_for(name)} -> HTTP {status}"); problems += 1
            print(f"{row['id']} {row['date']} {row['time']} Lisbon = {due_utc(row):%Y-%m-%d %H:%M} UTC "
                  f"{row['type']} {len(files)} file(s) [{row['status']}]")
        print("All good." if not problems else f"{problems} problem(s) found.")
        sys.exit(1 if problems else 0)

    if args[:1] == ["--dry-run"]:
        pid = args[1] if len(args) > 1 else "P03"
        row = next(r for r in rows if r["id"] == pid)
        cid = build(ig_id, row)
        print(f"DRY RUN OK: {pid} is ready on Instagram's side (container {cid}). Not published.")
        return

    now = datetime.now(timezone.utc)
    failed = 0
    for row in rows:
        if row["status"] != "pending":
            continue
        due = due_utc(row)
        if due > now:
            continue
        if now - due > MAX_LATE:
            row["status"] = "missed"
            save(rows)
            print(f"{row['id']}: more than {MAX_LATE.total_seconds() / 3600:g} hours late, marked missed (edit date and set status to pending to post it).")
            continue
        try:
            cid = build(ig_id, row)
            media_id = call("POST", f"{ig_id}/media_publish", {"creation_id": cid})["id"]
        except ApiError as e:
            print(f"{row['id']}: NOT published: {e}")
            failed += 1
            continue
        row["status"], row["instagram_id"] = "published", media_id
        save(rows)
        print(f"{row['id']}: published (Instagram media id {media_id}).")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
