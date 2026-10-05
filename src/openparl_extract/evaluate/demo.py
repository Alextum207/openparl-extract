"""Demo question: median days from submission to executive answer, per parliament, for one affair type.

Uses only API-metadata dates (procedural_history), so it needs no LLM. Affairs missing either date are counted, not guessed.
"""
import pandas as pd

from openparl_extract.models import Affair


def _first(a: Affair, state: str):
    ds = [e.date.value for e in a.procedural_history if e.state.value == state and e.date.value]
    return min(ds) if ds else None


def days_to_answer(affairs: list[Affair], affair_type: str = "interpellation") -> pd.DataFrame:
    rows = []
    for a in affairs:
        if a.affair_type.value != affair_type:
            continue
        s, r = _first(a, "submitted"), _first(a, "answered")
        rows.append({"body_key": a.source.body_key or a.source.parliament, "level": a.source.level.value,
                     "days": (r - s).days if s and r and r >= s else None})
    df = pd.DataFrame(rows, columns=["body_key", "level", "days"])
    g = df.groupby(["body_key", "level"])["days"]
    return pd.DataFrame({"n_affairs": g.size(), "n_with_both_dates": g.count(), "median_days": g.median()}).reset_index()
