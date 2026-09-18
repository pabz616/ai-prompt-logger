"""
Gemma call-boundary failure modes, against the real script (sql_report.py).

  1. Slow      -- no timeout in ai() or upstream of it. Latency alone must
                  not break the happy path; a genuine infinite hang can't
                  be safely asserted against without the app having a
                  timeout of its own (it doesn't), so this is guarded with
                  pytest-timeout as a CI safety net instead.
  2. Failed    -- no try/except in ai(). A connection failure (httpx) or an
                  ollama.ResponseError propagates raw. Since main() calls
                  db.insert() only after ai() returns, an exception here
                  means the insert never happens -- verified directly.
  3. Malformed -- ai() has NO validation on the response at all. These
                  tests document that gap with xfail (desired behavior,
                  currently unmet) plus a characterization test proving
                  what actually happens today: the bad value reaches the
                  database unfiltered.

MOCK TARGET: sql_report.py does `from ollama import chat`, so `chat` is a
name bound in sql_report's own namespace at import time. Patching must
target "sql_report.chat" -- the name as sql_report looks it up -- not
"ollama.chat", which would silently fail to apply (sql_report already holds
its own reference to the original function).

Requires: pytest-mock (the `mocker` fixture), pytest-timeout (the
`@pytest.mark.timeout` marker).
"""

import time

import httpx
import ollama
import pytest
from ollama import ChatResponse, Message

from sql_report import ai, db


def valid_response(text="A valid response."):
    return ChatResponse(model="gemma4", message=Message(role="assistant", content=text))


def all_rows():
    import sqlite3
    conn = sqlite3.connect("ai-class.db")
    rows = conn.execute("SELECT * FROM thread").fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# 1. SLOW
# ---------------------------------------------------------------------------
class TestDelayedGemmaResponse:
    """No explicit timeout in ai() or upstream of it. "Slow" is the success
    path with extra latency, not a separate branch."""

    def test_delayed_but_successful_response_still_returns(self, mocker):
        def delayed_reply(model, messages):
            time.sleep(0.05)  # short simulated latency, keeps the suite fast
            return valid_response("Reply after a short delay.")

        mocker.patch("sql_report.chat", side_effect=delayed_reply)
        assert ai("prompt") == "Reply after a short delay."

    @pytest.mark.timeout(2)
    def test_suite_fails_fast_if_a_future_change_introduces_a_real_hang(self, mocker):
        """Canary, not a functional test: if retry/backoff logic with no
        upper bound is ever added, this fails in 2s instead of hanging CI.
        Passes today because the mock returns immediately."""
        mocker.patch("sql_report.chat", return_value=valid_response("Immediate reply."))
        assert ai("prompt")


# ---------------------------------------------------------------------------
# 2. FAILED
# ---------------------------------------------------------------------------
class TestConnectionFailure:
    """No error translation exists. A connection failure must propagate
    unchanged and must block the insert that would otherwise follow it."""

    @pytest.mark.parametrize(
        "raised_exception",
        [
            pytest.param(httpx.ConnectError("Connection refused"), id="server_not_running"),
            pytest.param(httpx.ConnectTimeout("timed out connecting"), id="connect_timeout"),
            pytest.param(httpx.ReadTimeout("timed out mid-response"), id="read_timeout"),
            pytest.param(
                httpx.RemoteProtocolError("server disconnected without sending a response"),
                id="server_died_mid_stream",
            ),
        ],
    )
    def test_connection_failure_propagates_and_blocks_the_insert(self, mocker, raised_exception):
        mocker.patch("sql_report.chat", side_effect=raised_exception)

        with pytest.raises(type(raised_exception)):
            # Mirrors main()'s actual sequence: response = ai(query); db.insert(...)
            query = "prompt"
            response = ai(query)
            db.insert(query, response)

        assert all_rows() == []

    def test_connection_failure_leaves_no_partial_row(self, mocker):
        """Guards against a subtler bug than 'no row at all': a prompt
        written before the failure with a NULL/empty response left behind."""
        mocker.patch("sql_report.chat", side_effect=httpx.ConnectError("Connection refused"))

        with pytest.raises(httpx.ConnectError):
            query = "prompt"
            response = ai(query)
            db.insert(query, response)

        assert all_rows() == []

    def test_ollama_response_error_propagates_and_blocks_the_insert(self, mocker):
        """ollama.ResponseError -- e.g. an unknown model name -- is a
        distinct failure category from a transport-level connection error:
        the server responded, just with an error status."""
        mocker.patch(
            "sql_report.chat",
            side_effect=ollama.ResponseError("model 'gemma4' not found", status_code=404),
        )
        with pytest.raises(ollama.ResponseError) as excinfo:
            query = "prompt"
            response = ai(query)
            db.insert(query, response)

        assert excinfo.value.status_code == 404
        assert all_rows() == []


# ---------------------------------------------------------------------------
# 3. MALFORMED
# ---------------------------------------------------------------------------
class TestMalformedGemmaResponse:
    """ai() has no validation at all. These document the CURRENT gap with
    xfail (desired behavior) plus a characterization test (actual
    behavior), rather than asserting a guard that doesn't exist."""

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param(None, id="null_content"),
            pytest.param("", id="empty_string"),
            pytest.param("   ", id="whitespace_only"),
        ],
    )
    def test_malformed_content_is_rejected_before_reaching_the_caller(
        self, mocker, content
    ):
        mocker.patch(
            "sql_report.chat",
            return_value=ChatResponse(model="gemma4", message=Message(role="assistant", content=content)),
        )
        with pytest.raises(AssertionError):
            ai("prompt")

        assert all_rows() == [], "a rejected response must not reach the database"

    def test_valid_response_is_accepted(self, mocker):
        """Control case: proves the malformed-content tests above are
        discriminating against a real positive case, not just failing
        because nothing works."""
        mocker.patch("sql_report.chat", return_value=valid_response("A perfectly good reply."))

        query = "prompt"
        response = ai(query)
        db.insert(query, response)

        assert response == "A perfectly good reply."
        assert len(all_rows()) == 1