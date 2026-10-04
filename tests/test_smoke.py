import importlib

import pytest


@pytest.mark.parametrize(
    "name", ["", ".ingest", ".parse", ".segment", ".extract", ".verify", ".merge", ".evaluate", ".review"]
)
def test_import(name):
    importlib.import_module("openparl_extract" + name)
