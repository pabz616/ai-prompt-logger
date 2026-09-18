import os

import pytest

from sql_report import db


@pytest.fixture(autouse=True)
def isolated_working_directory(request, tmp_path, monkeypatch):
    if "uses_real_db" in request.keywords:
        yield
        return

    monkeypatch.chdir(tmp_path)
    os.makedirs("reports", exist_ok=True)
    db.create()
    yield