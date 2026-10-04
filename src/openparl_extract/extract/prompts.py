"""Prompt template loader: templates live in extract/prompts/<group>.v<N>.md (package data)."""
import re
from importlib.resources import files


def load_prompt(group: str, version: str | None = None) -> tuple[str, str]:
    """(template text, version). Highest vN unless `version` is given. Raises FileNotFoundError if missing."""
    d = files("openparl_extract.extract") / "prompts"
    found = {}
    for f in d.iterdir():
        m = re.fullmatch(rf"{re.escape(group)}\.(v(\d+))\.md", f.name)
        if m:
            found[m.group(1)] = (int(m.group(2)), f)
    if version is not None:
        if version not in found:
            raise FileNotFoundError(f"prompt template {group}.{version}.md not found (have: {sorted(found)})")
        v = version
    elif found:
        v = max(found, key=lambda k: found[k][0])
    else:
        raise FileNotFoundError(f"no prompt template for group {group!r}")
    text = found[v][1].read_text(encoding="utf-8")
    assert f"FIELD_GROUP: {group}" in text, f"template {group}.{v}.md lacks the 'FIELD_GROUP: {group}' line"
    return text, v
