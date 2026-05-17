#!/usr/bin/env python3
"""clickdoc — click-to-comment live documentation server.

A small stdlib-only HTTP server with a SQLite back-end that turns any
folder of HTML pages into a documentation site where any element marked
[data-anchor="..."] (or any free text selection) is annotatable in-place.
Annotations are stored locally and surfaced through a JSON API plus a
plain-text feed so AI assistants (Claude Code, Codex, Hermes, etc.)
running on the same machine can read and address remarks.

Design goals
------------
* zero runtime dependencies (Python 3.11+ stdlib only)
* one process, one SQLite file, one folder of static assets
* trivially mountable behind a reverse proxy / Kubernetes Gateway API
* agnostic of the project being documented: pages can live anywhere
  via the CLICKDOC_PAGES_DIR env var (overlay)

Environment
-----------
    CLICKDOC_LISTEN_HOST     bind address (default 0.0.0.0)
    CLICKDOC_LISTEN_PORT     bind port    (default 8088)
    CLICKDOC_DB_PATH         SQLite file path (default $XDG_DATA_HOME/clickdoc/annotations.db,
                             fallback to ./annotations.db next to this script)
    CLICKDOC_PAGES_DIR       overlay pages dir; checked FIRST, falls back
                             to the bundled ./pages dir of this script.
                             Allows separating framework (public) from
                             site content (private).
    CLICKDOC_STATIC_DIR      override the bundled static/ dir
    CLICKDOC_AUTHOR          default author tag on POST (default 'anon')
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent

LISTEN_HOST = os.environ.get("CLICKDOC_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("CLICKDOC_LISTEN_PORT", "8088"))
DEFAULT_AUTHOR = os.environ.get("CLICKDOC_AUTHOR", "anon")

PAGES_OVERLAY = Path(os.environ["CLICKDOC_PAGES_DIR"]).resolve() if os.environ.get("CLICKDOC_PAGES_DIR") else None
STATIC_OVERLAY = Path(os.environ["CLICKDOC_STATIC_DIR"]).resolve() if os.environ.get("CLICKDOC_STATIC_DIR") else None
PAGES_BUNDLED = (SCRIPT_DIR / "pages").resolve()
STATIC_BUNDLED = (SCRIPT_DIR / "static").resolve()


def _resolve_db_path() -> Path:
    env = os.environ.get("CLICKDOC_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    candidate = Path(xdg) / "clickdoc" / "annotations.db"
    try:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate
    except Exception:
        return SCRIPT_DIR / "annotations.db"


DB_PATH = _resolve_db_path()
_DB_LOCK = threading.Lock()

# Annotation lifecycle — a single comment travels these stages as agents act on it.
# Designed to be SIMPLE and ordered (open → triaged → refined → reviewed → final).
# 'final' means: the comment has been triaged, codex-refined, oracle-reviewed,
# and the engendered actions/specs are recorded; the comment is sprint-ready.
LIFECYCLE_STAGES = ("open", "triaged", "refined", "reviewed", "final")


def db():
    con = sqlite3.connect(DB_PATH, isolation_level=None, timeout=5.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.row_factory = sqlite3.Row
    return con


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _DB_LOCK, db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS annotations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              author TEXT NOT NULL DEFAULT 'anon',
              page TEXT NOT NULL,
              anchor TEXT,
              line_excerpt TEXT,
              type TEXT NOT NULL CHECK(type IN ('comment','spec','precision')),
              comment TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','addressed')),
              response TEXT,
              lifecycle TEXT NOT NULL DEFAULT 'open',
              lifecycle_log TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS annotations_page_idx     ON annotations(page);
            CREATE INDEX IF NOT EXISTS annotations_status_idx   ON annotations(status);
            CREATE INDEX IF NOT EXISTS annotations_created_idx  ON annotations(created_at);
            CREATE INDEX IF NOT EXISTS annotations_lifecycle_idx ON annotations(lifecycle);
            """
        )
        # Best-effort migration for older DBs that don't yet have the lifecycle columns.
        # SQLite is permissive; we attempt each ALTER independently and swallow "duplicate column" errors.
        for stmt in (
            "ALTER TABLE annotations ADD COLUMN lifecycle TEXT NOT NULL DEFAULT 'open'",
            "ALTER TABLE annotations ADD COLUMN lifecycle_log TEXT NOT NULL DEFAULT ''",
        ):
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_overlay(rel: str, overlay: Path | None, bundled: Path) -> Path | None:
    """Find <rel> first in overlay, then in bundled. Refuse path-escape attempts."""
    for root in (overlay, bundled):
        if root is None:
            continue
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None  # path traversal attempt
        if candidate.is_file():
            return candidate
    return None


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "clickdoc/1.0"

    def _send_json(self, status: int, body):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, status: int, body: str, content_type: str = "text/plain; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _read_json(self):
        try:
            ln = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            return None
        if ln <= 0:
            return {}
        raw = self.rfile.read(ln)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def _err(self, code: int, msg: str):
        self._send_json(code, {"error": msg})

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s %s\n" % (self.log_date_time_string(), self.address_string(), fmt % args))

    # ---- routing

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/":
            self.send_response(302)
            self.send_header("Location", "/pages/index.html")
            self.end_headers()
            return
        if p == "/api/health":
            return self._send_json(200, {"status": "ok"})
        if p == "/api/annotations":
            return self.api_list(parse_qs(u.query))
        if p == "/api/feed":
            return self.api_feed(parse_qs(u.query))
        if p == "/api/changes":
            return self.api_changes(parse_qs(u.query))
        if p.startswith("/pages/"):
            return self.serve_overlay(p[len("/pages/"):], PAGES_OVERLAY, PAGES_BUNDLED)
        if p.startswith("/static/"):
            return self.serve_overlay(p[len("/static/"):], STATIC_OVERLAY, STATIC_BUNDLED)
        return self._err(404, "not found")

    def do_POST(self):
        if self.path == "/api/annotations":
            return self.api_create()
        return self._err(404, "not found")

    def do_PATCH(self):
        if self.path.startswith("/api/annotations/"):
            try:
                aid = int(self.path.rsplit("/", 1)[1])
            except Exception:
                return self._err(400, "bad id")
            return self.api_update(aid)
        return self._err(404, "not found")

    def do_DELETE(self):
        if self.path.startswith("/api/annotations/"):
            try:
                aid = int(self.path.rsplit("/", 1)[1])
            except Exception:
                return self._err(400, "bad id")
            return self.api_delete(aid)
        return self._err(404, "not found")

    # ---- static

    def serve_overlay(self, rel: str, overlay: Path | None, bundled: Path):
        path = _resolve_overlay(rel, overlay, bundled)
        if path is None:
            return self._err(404, "not found")
        ctype = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ---- annotations API

    def api_list(self, qs):
        clauses, args = [], []
        if "status" in qs and qs["status"]:
            v = qs["status"][0]
            if v not in ("open", "addressed"):
                return self._err(400, "status must be open|addressed")
            clauses.append("status=?"); args.append(v)
        if "lifecycle" in qs and qs["lifecycle"]:
            v = qs["lifecycle"][0]
            if v not in LIFECYCLE_STAGES:
                return self._err(400, f"lifecycle must be one of {','.join(LIFECYCLE_STAGES)}")
            clauses.append("lifecycle=?"); args.append(v)
        if "page" in qs and qs["page"]:
            clauses.append("page=?"); args.append(qs["page"][0])
        if "type" in qs and qs["type"]:
            v = qs["type"][0]
            if v not in ("comment", "spec", "precision"):
                return self._err(400, "type must be comment|spec|precision")
            clauses.append("type=?"); args.append(v)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM annotations{where} ORDER BY id DESC"
        with _DB_LOCK, db() as con:
            rows = [dict(r) for r in con.execute(sql, args).fetchall()]
        return self._send_json(200, rows)

    def api_create(self):
        body = self._read_json()
        if body is None:
            return self._err(400, "bad json")
        page = (body.get("page") or "").strip()
        comment = (body.get("comment") or "").strip()
        ctype = (body.get("type") or "comment").strip()
        if ctype not in ("comment", "spec", "precision"):
            return self._err(400, "type must be comment|spec|precision")
        if not page:
            return self._err(400, "page required")
        if not comment:
            return self._err(400, "comment required")
        anchor = (body.get("anchor") or "").strip() or None
        line = (body.get("line_excerpt") or "").strip() or None
        author = (body.get("author") or DEFAULT_AUTHOR).strip() or DEFAULT_AUTHOR
        ts = now_iso()
        with _DB_LOCK, db() as con:
            cur = con.execute(
                "INSERT INTO annotations(created_at, updated_at, author, page, anchor, line_excerpt, type, comment) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (ts, ts, author, page, anchor, line, ctype, comment),
            )
            aid = cur.lastrowid
            row = dict(con.execute("SELECT * FROM annotations WHERE id=?", (aid,)).fetchone())
        return self._send_json(201, row)

    def api_update(self, aid: int):
        body = self._read_json()
        if body is None:
            return self._err(400, "bad json")
        fields, args = [], []
        lifecycle_transition = None  # (new_stage, by) — appended to lifecycle_log if set
        if "status" in body:
            v = body["status"]
            if v not in ("open", "addressed"):
                return self._err(400, "status must be open|addressed")
            fields.append("status=?"); args.append(v)
        if "lifecycle" in body:
            v = body["lifecycle"]
            if v not in LIFECYCLE_STAGES:
                return self._err(400, f"lifecycle must be one of {','.join(LIFECYCLE_STAGES)}")
            fields.append("lifecycle=?"); args.append(v)
            lifecycle_transition = (v, (body.get("lifecycle_by") or "agent").strip())
            # Convenience: 'final' implies status=addressed; we still allow status= to override.
            if v == "final" and "status" not in body:
                fields.append("status=?"); args.append("addressed")
        if "response" in body:
            fields.append("response=?"); args.append(body["response"] or None)
        if "author" in body:
            fields.append("author=?"); args.append((body["author"] or DEFAULT_AUTHOR).strip())
        if not fields and lifecycle_transition is None:
            return self._err(400, "nothing to update")
        fields.append("updated_at=?"); args.append(now_iso())
        # Append to lifecycle_log if a transition was requested.
        if lifecycle_transition is not None:
            new_stage, by = lifecycle_transition
            with _DB_LOCK, db() as con:
                row = con.execute("SELECT lifecycle_log FROM annotations WHERE id=?", (aid,)).fetchone()
                if row is None:
                    return self._err(404, "not found")
                existing = row["lifecycle_log"] or ""
                entry = f"{now_iso()} | {new_stage} | by={by}"
                if "lifecycle_note" in body and body["lifecycle_note"]:
                    entry += f" | note={str(body['lifecycle_note'])[:200]}"
                new_log = (existing + "\n" + entry).strip() if existing else entry
                fields.append("lifecycle_log=?"); args.append(new_log)
        args.append(aid)
        with _DB_LOCK, db() as con:
            cur = con.execute(f"UPDATE annotations SET {', '.join(fields)} WHERE id=?", args)
            if cur.rowcount == 0:
                return self._err(404, "not found")
            row = dict(con.execute("SELECT * FROM annotations WHERE id=?", (aid,)).fetchone())
        return self._send_json(200, row)

    def api_delete(self, aid: int):
        with _DB_LOCK, db() as con:
            cur = con.execute("DELETE FROM annotations WHERE id=?", (aid,))
            if cur.rowcount == 0:
                return self._err(404, "not found")
        return self._send_json(200, {"deleted": aid})

    def api_changes(self, qs):
        """Unified change feed for the doc.

        Aggregates three event sources into one chronological stream:
          - annotation_created  · ju (or anyone) leaves a remark
          - annotation_addressed · an agent PATCHes status=addressed
          - page_edited         · an HTML file under pages/ was modified
                                  (file mtime; we cannot tell who edited it
                                  without a git layer, so 'by' is 'unknown')

        Query params:
          since=<duration>  e.g. 1h, 24h, 7d, 30d, all  (default 7d)
          kind=<kind>       optional filter, comma-separated
          limit=<n>         cap the number of returned events (default 200)
        """
        since = (qs.get("since") or ["7d"])[0].strip().lower()
        cutoff = self._parse_duration_cutoff(since)
        kinds = set((qs.get("kind") or [""])[0].split(",")) if (qs.get("kind") or [""])[0] else None
        try:
            limit = max(1, min(int((qs.get("limit") or ["200"])[0]), 1000))
        except ValueError:
            limit = 200

        events = []

        # 1. annotation events from SQLite
        with _DB_LOCK, db() as con:
            cur = con.execute(
                "SELECT id, created_at, updated_at, status, type, author, page, anchor, line_excerpt, comment, response, lifecycle, lifecycle_log FROM annotations"
            )
            for r in cur.fetchall():
                created = r["created_at"]
                if (cutoff is None or created >= cutoff) and (kinds is None or "annotation_created" in kinds):
                    events.append({
                        "kind": "annotation_created",
                        "at": created,
                        "id": r["id"],
                        "type": r["type"],
                        "by": r["author"],
                        "page": r["page"],
                        "anchor": r["anchor"],
                        "excerpt": r["line_excerpt"],
                        "comment": r["comment"],
                        "lifecycle": r["lifecycle"],
                    })
                updated = r["updated_at"]
                if r["status"] == "addressed" and updated and updated != created:
                    if (cutoff is None or updated >= cutoff) and (kinds is None or "annotation_addressed" in kinds):
                        events.append({
                            "kind": "annotation_addressed",
                            "at": updated,
                            "id": r["id"],
                            "type": r["type"],
                            "by": "agent",
                            "page": r["page"],
                            "anchor": r["anchor"],
                            "excerpt": r["line_excerpt"],
                            "response": r["response"],
                            "lifecycle": r["lifecycle"],
                        })
                # 1b. lifecycle transitions parsed from lifecycle_log
                # Each log line is: "ISO | stage | by=… | note=…"
                if r["lifecycle_log"] and (kinds is None or "lifecycle_transition" in kinds):
                    for line in r["lifecycle_log"].splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) < 2:
                            continue
                        ts, stage = parts[0], parts[1]
                        if cutoff is not None and ts < cutoff:
                            continue
                        by = "agent"
                        note = None
                        for extra in parts[2:]:
                            if extra.startswith("by="):
                                by = extra[3:]
                            elif extra.startswith("note="):
                                note = extra[5:]
                        events.append({
                            "kind": "lifecycle_transition",
                            "at": ts,
                            "id": r["id"],
                            "type": r["type"],
                            "by": by,
                            "page": r["page"],
                            "anchor": r["anchor"],
                            "stage": stage,
                            "lifecycle": r["lifecycle"],
                            "note": note,
                        })

        # 2. file mtime events from pages overlay + bundled
        seen_paths = set()
        for root in (PAGES_OVERLAY, PAGES_BUNDLED):
            if root is None or not root.exists():
                continue
            for path in root.rglob("*.html"):
                rel = str(path.relative_to(root))
                if rel in seen_paths:
                    continue  # overlay wins, skip bundled twin
                seen_paths.add(rel)
                try:
                    st = path.stat()
                except OSError:
                    continue
                mt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
                if cutoff is not None and mt < cutoff:
                    continue
                if kinds is not None and "page_edited" not in kinds:
                    continue
                events.append({
                    "kind": "page_edited",
                    "at": mt,
                    "page": "/pages/" + rel,
                    "size_bytes": st.st_size,
                    "by": "unknown",
                })

        events.sort(key=lambda e: e["at"], reverse=True)
        return self._send_json(200, events[:limit])

    @staticmethod
    def _parse_duration_cutoff(since: str):
        """Parse '1h' / '24h' / '7d' / '30d' / 'all' → ISO cutoff or None."""
        if since in ("all", "0", "*"):
            return None
        if not since:
            return None
        try:
            n = int(since[:-1])
            unit = since[-1]
        except (ValueError, IndexError):
            return None
        seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}.get(unit)
        if not seconds:
            return None
        from datetime import timedelta
        cutoff_dt = datetime.now(timezone.utc) - timedelta(seconds=n * seconds)
        return cutoff_dt.isoformat(timespec="seconds")

    def api_feed(self, qs):
        clauses, args = [], []
        if "status" in qs and qs["status"]:
            clauses.append("status=?"); args.append(qs["status"][0])
        else:
            clauses.append("status='open'")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with _DB_LOCK, db() as con:
            rows = [dict(r) for r in con.execute(f"SELECT * FROM annotations{where} ORDER BY id ASC", args).fetchall()]
        out = [
            f"# clickdoc annotation feed — {len(rows)} item(s) — generated {now_iso()}",
            "# PATCH /api/annotations/<id> with {status:'addressed', response:'...'} when done.",
            "",
        ]
        for r in rows:
            out.append(f"--- id={r['id']} type={r['type']} status={r['status']} author={r['author']} created={r['created_at']} ---")
            out.append(f"page:    {r['page']}")
            if r.get("anchor"):
                out.append(f"anchor:  #{r['anchor']}")
            if r.get("line_excerpt"):
                out.append(f"excerpt: {r['line_excerpt'][:240]}")
            out.append(f"comment: {r['comment']}")
            if r.get("response"):
                out.append(f"response: {r['response']}")
            out.append("")
        return self._send_text(200, "\n".join(out))


def main():
    init_db()
    srv = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"[clickdoc] listening on http://{LISTEN_HOST}:{LISTEN_PORT}", file=sys.stderr)
    print(f"[clickdoc] db:           {DB_PATH}", file=sys.stderr)
    print(f"[clickdoc] pages overlay: {PAGES_OVERLAY or '(none)'}", file=sys.stderr)
    print(f"[clickdoc] pages bundled: {PAGES_BUNDLED}", file=sys.stderr)
    print(f"[clickdoc] static overlay: {STATIC_OVERLAY or '(none)'}", file=sys.stderr)
    print(f"[clickdoc] static bundled: {STATIC_BUNDLED}", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
