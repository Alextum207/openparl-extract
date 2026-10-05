"""Local HTTP API of the review app (stdlib only, 127.0.0.1 only, no network access at runtime)."""
import json
import mimetypes
import re
import sys
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from openparl_extract.evaluate.gold import GoldDoc
from openparl_extract.ingest.store import load_manifest
from openparl_extract.models import Affair
from openparl_extract.parse.blocks import ParsedDoc, load_parsed
from openparl_extract.review.i18n import LANGS, STRINGS, t
from openparl_extract.review.questions import build_question
from openparl_extract.review.render import page_blocks, page_size, render_page
from openparl_extract.review.store import GoldStore, ReviewError

HOST = "127.0.0.1"
STATIC = Path(__file__).parent / "static"
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_BODY = 1_000_000


class ApiError(Exception):
    def __init__(self, status: int, key: str):
        self.status, self.key = status, key


def clean_reviewer(name) -> str:
    if not isinstance(name, str):
        raise ApiError(400, "err.bad_reviewer")
    s = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf")).strip()[:40]
    if not s:
        raise ApiError(400, "err.bad_reviewer")
    return s


def _langset(v: str | None) -> set | None:
    return set(filter(None, (v or "").split(","))) or None


class Resources:
    """Where the files of one gold doc live (paths are built from validated gold fields, never from the URL)."""

    def __init__(self, data_dir: Path):
        self.data = Path(data_dir)

    def _dir(self, stage: str, doc: GoldDoc) -> Path | None:
        for part in (doc.body_key, doc.affair_id):
            if not _SAFE.match(part) or part in (".", ".."):
                return None
        return self.data / stage / doc.body_key / doc.affair_id

    def pdf(self, doc: GoldDoc) -> Path | None:
        d = self._dir("raw", doc)
        try:
            p = d / f"doc_{int(load_manifest(d / 'manifest.json')['primary_doc_id'])}.pdf"
        except (TypeError, ValueError, KeyError, OSError):
            return None
        return p if p.is_file() else None

    def parsed(self, doc: GoldDoc) -> ParsedDoc | None:
        d = self._dir("parsed", doc)
        try:
            return load_parsed(d / "parsed.json")
        except (TypeError, ValueError, OSError):
            return None

    def affair(self, doc: GoldDoc) -> Affair | None:
        d = self._dir("output", doc)
        try:
            return Affair.model_validate_json((d / "affair.json").read_text(encoding="utf-8"))
        except (TypeError, ValueError, OSError):
            return None


class Handler(BaseHTTPRequestHandler):
    server_version = "ReviewApp"

    def log_message(self, *a):  # quiet
        pass

    # ---- plumbing ----
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _dispatch(self, method: str) -> None:
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        body: dict = {}
        port = self.server.server_address[1]
        # consume the body before any early rejection: closing with unread data makes Windows reset the connection
        # before the client can read the 403/415
        try:
            declared = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            declared = 0
        payload = self.rfile.read(declared) if method == "POST" and 0 < declared <= MAX_BODY else b""
        # DNS-rebinding / CSRF guard: only our own origin may talk to us
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}") or self.headers.get(
                "Origin") not in (None, f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            return self._json({"error": t(self.server.lang_default, "err.forbidden")}, 403)
        if method == "POST":
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                return self._json({"error": t(self.server.lang_default, "err.bad_request")}, 415)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 <= n <= MAX_BODY:
                    raise ValueError
                body = json.loads(payload or b"{}")
                if not isinstance(body, dict):
                    raise TypeError
            except (ValueError, TypeError):
                return self._json({"error": t(q.get("lang", self.server.lang_default), "err.bad_request")}, 400)
        lang = str(body.get("lang") or q.get("lang") or self.server.lang_default)
        try:
            self._route(method, unquote(u.path), q, body, lang)
        except ApiError as e:
            self._json({"error": t(lang, e.key)}, e.status)
        except ReviewError as e:
            self._json({"error": t(lang, e.key)},
                       409 if e.key == "err.undo_conflict" else 404 if method == "GET" else 400)
        except Exception as e:  # noqa: BLE001  never leak a traceback to the client
            print(f"review app: {type(e).__name__}: {e}", file=sys.stderr)
            self._json({"error": t(lang, "err.server")}, 500)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    # ---- routes ----
    def _route(self, method: str, path: str, q: dict, body: dict, lang: str) -> None:
        st: GoldStore = self.server.store
        if method == "GET" and path in ("/", "/index.html"):
            return self._static("index.html")
        if method == "GET" and path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if method == "GET" and path == "/api/i18n":
            return self._json(STRINGS.get(lang, STRINGS["en"]))
        if method == "GET" and path == "/api/docs":
            return self._json([d.model_dump() for d in st.docs(_langset(q.get("languages")))])
        if method == "GET" and path == "/api/progress":
            return self._json(st.progress(q.get("reviewer", ""), _langset(q.get("languages"))))
        if method == "GET" and path == "/api/question":
            return self._question(q, lang)
        if method == "POST" and path == "/api/answer":
            if not all(isinstance(body.get(k), str) for k in ("doc", "field", "verdict")):
                raise ApiError(400, "err.bad_request")
            try:
                st.get(body["doc"])
            except ReviewError:  # unknown doc is a client error on POST
                raise ApiError(400, "err.unknown_doc") from None
            gid = body.get("gold_block_id")
            parsed = self.server.res.parsed(st.get(body["doc"]))
            if isinstance(gid, str) and parsed is not None and gid not in {b.id for b in parsed.blocks}:
                raise ApiError(400, "err.unknown_block")
            e = st.apply_answer(body["doc"], body["field"], body["verdict"], clean_reviewer(body.get("reviewer")),
                                body.get("gold_value"), body.get("gold_block_id"), body.get("note"))
            return self._json(e.model_dump())
        if method == "POST" and path == "/api/undo":
            e = st.undo(clean_reviewer(body.get("reviewer")))
            if e is None:
                raise ApiError(404, "err.nothing_to_undo")
            return self._json(e.model_dump())
        if method == "GET" and path in ("/api/page", "/api/blocks"):
            return self._page(path, q)
        raise ApiError(404, "err.not_found")

    def _static(self, name: str) -> None:
        f = STATIC / name
        if (not name or any(c in name for c in "/\\:") or name.startswith(".")
                or f.resolve().parent != STATIC.resolve() or not f.is_file()):
            raise ApiError(404, "err.not_found")
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))

    def _question(self, q: dict, lang: str) -> None:
        st: GoldStore = self.server.store
        langs = _langset(q.get("languages"))
        if "doc" in q:
            ref = (q["doc"], q.get("field", ""))
        else:
            ref = st.next_question_ref(q.get("reviewer", ""), langs, q.get("include_unsure") == "1")
        if ref is None:
            return self._json({"done": True, "summary": st.summary(langs),
                               "progress": st.progress(q.get("reviewer", ""), langs)})
        doc = st.get(ref[0])
        entry = next((e for e in doc.entries if e.field == ref[1]), None)
        if entry is None:
            raise ApiError(404, "err.unknown_field")
        r = self.server.res
        self._json(build_question(doc, entry, r.affair(doc), r.parsed(doc), lang, ref[0]).model_dump())

    def _page(self, path: str, q: dict) -> None:
        doc = self.server.store.get(q.get("doc", ""))
        try:
            page, scale = int(q.get("page", "1")), min(4.0, max(0.5, float(q.get("scale", "1.5"))))
        except ValueError:
            raise ApiError(400, "err.bad_page") from None
        r = self.server.res
        pdf = r.pdf(doc)
        if path == "/api/page":
            if pdf is None:
                raise ApiError(404, "err.no_pdf")
            try:
                return self._send(200, render_page(pdf, page, scale), "image/png")
            except ValueError:
                raise ApiError(400, "err.bad_page") from None
        parsed = r.parsed(doc)
        if parsed is None:
            raise ApiError(404, "err.no_parsed")
        try:
            w, h = page_size(pdf, page) if pdf else (None, None)
        except ValueError:
            raise ApiError(400, "err.bad_page") from None
        self._json({"blocks": page_blocks(parsed, page), "width": w, "height": h})


def make_server(data_dir: Path, gold_dir: Path, port: int = 8765, lang_default: str = "de"):
    srv = ThreadingHTTPServer((HOST, port), Handler)
    assert srv.server_address[0] == "127.0.0.1", "review app must only listen on localhost"
    srv.daemon_threads = True
    srv.store, srv.res = GoldStore(gold_dir, data_dir), Resources(data_dir)
    srv.lang_default = lang_default if lang_default in LANGS else "de"
    return srv, f"http://{HOST}:{srv.server_address[1]}"


def serve(data_dir: Path, gold_dir: Path, port: int = 8765, lang_default: str = "de", on_ready=None) -> None:
    srv, url = make_server(data_dir, gold_dir, port, lang_default)
    if on_ready:
        on_ready(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
