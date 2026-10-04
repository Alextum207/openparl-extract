"""Gold files on disk: atomic answers, per-reviewer undo, queue and progress. Every change is logged."""
import json
import os
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from openparl_extract.evaluate.gold import GoldDoc, GoldEntry
from openparl_extract.evaluate.metrics import family
from openparl_extract.models import DecisionOutcome
from openparl_extract.review.i18n import t
from openparl_extract.review.questions import field_rank

LOG_NAME = ".review_log.jsonl"
MAX_NOTE, MAX_GOLD = 500, 5000
VERDICTS = ("correct", "wrong", "not_in_document", "unsure")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ReviewError(ValueError):
    """Validation error carrying an i18n key (`err.*`) so the API can answer in the reviewer's language."""

    def __init__(self, key: str):
        super().__init__(t("en", key))
        self.key = key


class DocSummary(BaseModel):
    doc_key: str
    affair_id: str
    body_key: str
    language: str
    level: str
    n_entries: int
    n_reviewed: int
    n_open: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GoldStore:
    def __init__(self, gold_dir: Path, data_dir: Path):
        self.gold_dir, self.data_dir = Path(gold_dir), Path(data_dir)
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[tuple, GoldDoc]] = {}  # doc_key -> (mtime_ns, doc)

    # ---- loading ----
    def keys(self) -> list[str]:
        return sorted(p.stem for p in self.gold_dir.glob("*.json")) if self.gold_dir.exists() else []

    def get(self, doc_key: str) -> GoldDoc:
        """Copy of the gold doc (re-read when the file changed). ReviewError(err.unknown_doc) if absent."""
        if doc_key not in self.keys():
            raise ReviewError("err.unknown_doc")
        p = self.gold_dir / f"{doc_key}.json"
        with self._lock:
            st = p.stat()
            m = (st.st_mtime_ns, st.st_size, st.st_ino)  # coarse mtimes (Windows/OneDrive) alone miss rewrites
            if doc_key not in self._cache or self._cache[doc_key][0] != m:
                self._cache[doc_key] = (m, GoldDoc.model_validate_json(p.read_text(encoding="utf-8")))
            return self._cache[doc_key][1].model_copy(deep=True)

    def ordered(self, doc_key: str) -> list[GoldEntry]:
        return sorted(self.get(doc_key).entries, key=lambda e: field_rank(e.field))  # stable

    def _keys_for(self, languages) -> list[str]:
        return [k for k in self.keys() if not languages or self.get(k).language in languages]

    # ---- writing ----
    def _write(self, doc_key: str, doc: GoldDoc) -> None:
        p = self.gold_dir / f"{doc_key}.json"
        tmp = self.gold_dir / f".{doc_key}.json.tmp"
        tmp.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, p)
        self._cache.pop(doc_key, None)

    def _log(self, reviewer, doc_key, field, action, before, after) -> None:
        line = {"ts": _now(), "reviewer": reviewer, "doc_key": doc_key, "field": field, "action": action,
                "before": before, "after": after}
        with (self.gold_dir / LOG_NAME).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    def apply_answer(self, doc_key: str, field: str, verdict: str, reviewer: str, gold_value: str | None = None,
                     gold_block_id: str | None = None, note: str | None = None) -> GoldEntry:
        if not all(isinstance(x, str) for x in (doc_key, field, reviewer)) or not all(
                x is None or isinstance(x, str) for x in (gold_value, gold_block_id, note)):
            raise ReviewError("err.bad_request")
        if verdict not in VERDICTS:
            raise ReviewError("err.invalid_verdict")
        if len(note or "") > MAX_NOTE or len(gold_value or "") > MAX_GOLD or len(gold_block_id or "") > 100:
            raise ReviewError("err.too_long")
        with self._lock:
            doc = self.get(doc_key)
            entry = next((e for e in doc.entries if e.field == field), None)
            if entry is None:
                raise ReviewError("err.unknown_field")
            if gold_value is not None:
                if field == "decision.outcome" and gold_value not in {o.value for o in DecisionOutcome}:
                    raise ReviewError("err.bad_vocab")
                if field == "decision.date":
                    try:
                        date.fromisoformat(gold_value)
                    except ValueError:
                        raise ReviewError("err.bad_date") from None
                    if not _ISO.match(gold_value):
                        raise ReviewError("err.bad_date")
            if entry.pipeline_value is None and verdict == "correct":  # nothing to confirm
                raise ReviewError("err.invalid_verdict")
            if entry.pipeline_value is None and verdict == "wrong" and not (gold_value or gold_block_id):
                raise ReviewError("err.gold_required")
            before = entry.model_dump()
            entry.verdict, entry.reviewer, entry.timestamp = verdict, reviewer, _now()
            entry.gold_value = gold_value if verdict == "wrong" else None
            entry.gold_block_id = gold_block_id if verdict == "wrong" else None
            entry.note = note
            GoldEntry.model_validate(entry.model_dump())  # assignments are not validated by pydantic
            self._write(doc_key, doc)
            self._log(reviewer, doc_key, field, "answer", before, entry.model_dump())
            return entry

    def _undo_stack(self, reviewer: str) -> list[dict]:
        p = self.gold_dir / LOG_NAME
        stack: list[dict] = []
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                r = json.loads(ln)
                if r["reviewer"] != reviewer:
                    continue
                stack.append(r) if r["action"] == "answer" else (stack.pop() if stack else None)
        return stack

    def undo(self, reviewer: str) -> GoldEntry | None:
        with self._lock:
            stack = self._undo_stack(reviewer)
            if not stack:
                return None
            r = stack[-1]
            try:
                doc = self.get(r["doc_key"])
                i = next(i for i, e in enumerate(doc.entries) if e.field == r["field"])
            except (ReviewError, StopIteration):
                raise ReviewError("err.undo_conflict") from None
            current = doc.entries[i].model_dump()
            if current != r["after"]:  # someone answered this field after us: do not wipe their answer
                raise ReviewError("err.undo_conflict")
            doc.entries[i] = GoldEntry.model_validate(r["before"])
            self._write(r["doc_key"], doc)
            self._log(reviewer, r["doc_key"], r["field"], "undo", current, r["before"])
            return doc.entries[i]

    # ---- queue / progress ----
    def docs(self, languages: set | None) -> list[DocSummary]:
        out = []
        for k in self._keys_for(languages):
            d = self.get(k)
            n_open = sum(e.verdict == "unreviewed" for e in d.entries)
            out.append(DocSummary(doc_key=k, affair_id=d.affair_id, body_key=d.body_key, language=d.language.value,
                                  level=d.level.value, n_entries=len(d.entries),
                                  n_reviewed=len(d.entries) - n_open, n_open=n_open))
        return out

    def progress(self, reviewer: str, languages: set | None) -> dict:
        ds = self.docs(languages)
        unsure = sum(e.verdict == "unsure" for d in ds for e in self.get(d.doc_key).entries)
        total = sum(d.n_entries for d in ds)
        return {"docs_total": len(ds), "docs_done": sum(d.n_open == 0 and not self._has_unsure(d.doc_key) for d in ds),
                "questions_total": total, "questions_done": sum(d.n_reviewed for d in ds) - unsure,
                "questions_unsure": unsure}

    def _has_unsure(self, doc_key: str) -> bool:
        return any(e.verdict == "unsure" for e in self.get(doc_key).entries)

    def next_question_ref(self, reviewer: str, languages: set | None, include_unsure: bool = False):
        keys = self._keys_for(languages)
        for want in ("unreviewed",) + (("unsure",) if include_unsure else ()):
            for k in keys:
                for e in self.ordered(k):
                    if e.verdict == want:
                        return k, e.field
        return None

    def summary(self, languages: set | None) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for k in self._keys_for(languages):
            for e in self.get(k).entries:
                if e.verdict != "unreviewed":
                    c = out.setdefault(family(e.field), dict.fromkeys(VERDICTS, 0))
                    c[e.verdict] += 1
        return out
