import sqlite3
import os
import pytest
from utils.test_data import DB
from ollama import ChatResponse, Message
from sql_report import db, report


@pytest.fixture(autouse=True)
def isolated_working_directory(tmp_path, monkeypatch):
    """Every test gets its own directory, so "ai-class.db" (hardcoded in
    db.create/db.insert) and "./reports/ai-report-clean.html" (hardcoded in
    report()) never touch the real project files."""
    monkeypatch.chdir(tmp_path)
    os.makedirs("reports", exist_ok=True)
    db.create()
    yield
 
    
def insert_thread_record(conn, query, response):
    conn = sqlite3.connect(DB)
    conn.execute("INSERT INTO thread(query, response) VALUES (?, ?)", (query, response),)
    conn.commit()


def _table_names(conn):
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def all_rows():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT * FROM thread").fetchall()
    conn.close()
    return rows


def _thread_row_count(conn):
    return conn.execute("SELECT COUNT(*) FROM thread").fetchone()[0]


def _thread_columns(conn):
    conn = sqlite3.connect(DB)
    return [row[1] for row in conn.execute("PRAGMA table_info(thread)").fetchall()]


def valid_response(text="A valid response."):
    return ChatResponse(model="gemma4", message=Message(role="assistant", content=text))


INJECTION_PAYLOADS = [
    pytest.param("'); DROP TABLE thread; --", id="stacked_drop_table"),
    pytest.param("1; DELETE FROM thread; --", id="stacked_delete_all"),
    pytest.param("' OR '1'='1", id="tautology_or_true"),
    pytest.param("' OR 1=1--", id="tautology_or_true_dash_comment"),
    pytest.param("admin'--", id="comment_truncation"),
    pytest.param("' UNION SELECT name, sql FROM sqlite_master--", id="union_schema_exfiltration",),
    pytest.param("'; ATTACH DATABASE '/tmp/pwn.db' AS pwn; --", id="attach_database"),
    pytest.param("' AND (SELECT COUNT(*) FROM sqlite_master) > 0--", id="boolean_blind"),
    pytest.param("'||(SELECT sqlite_version())||'", id="function_call_concat"),
    pytest.param("DrOp TaBlE thread;", id="case_variation_bypass_attempt"),
    pytest.param("'; /**/DROP/**/TABLE/**/thread;--", id="comment_obfuscated_keywords"),
    pytest.param("' OR ''='", id="empty_string_tautology"),
    pytest.param("query\x00'; DROP TABLE thread;--", id="embedded_null_byte"),
    pytest.param("'; DROP TABLE thread; \uFF1B--", id="unicode_fullwidth_semicolon"),
    pytest.param("%27%20OR%20%271%27%3D%271", id="url_encoded_tautology_literal"),
]


class TestSQLInjection:
    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_malicious_query_field_stored_as_literal_data(self, payload):
        with sqlite3.connect(DB) as conn:
            tables_before = _table_names(conn)
            count_before = _thread_row_count(conn)

            insert_thread_record(conn, payload, "benign response")
            
            stored = conn.execute("SELECT query, response FROM thread WHERE query = ?", (payload,)).fetchone()

            assert stored is not None, "payload was not stored verbatim -- possible interpretation as SQL"
            assert stored[0] == payload
            assert _thread_row_count(conn) == count_before + 1
            assert _table_names(conn) == tables_before

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_malicious_response_field_stored_as_literal_data(self, payload):
        with sqlite3.connect(DB) as conn:
            tables_before = _table_names(conn)
            count_before = _thread_row_count(conn)

            insert_thread_record(conn, "benign prompt", payload)

            stored = conn.execute("SELECT query, response FROM thread WHERE response = ?", (payload,)).fetchone()

            assert stored is not None
            assert stored[1] == payload
            assert _thread_row_count(conn) == count_before + 1
            assert _table_names(conn) == tables_before

    def test_malicious_payload_in_both_fields_simultaneously(self):
        query_payload = "'; DROP TABLE thread; --"
        response_payload = "' UNION SELECT sql, name FROM sqlite_master--"

        with sqlite3.connect(DB) as conn:
            tables_before = _table_names(conn)

            insert_thread_record(conn, query_payload, response_payload)

            row = conn.execute(
                "SELECT query, response FROM thread WHERE query = ?", (query_payload,)
            ).fetchone()

            assert row == (query_payload, response_payload)
            assert _table_names(conn) == tables_before

    def test_schema_and_column_structure_unchanged_after_injection_attempts(self):
        """Runs every payload back-to-back and checks the schema exactly once
        at the end -- catches slow/cumulative corruption that a per-payload
        check might miss (e.g. a column silently added or dropped)."""
        with sqlite3.connect(DB) as conn:
            columns_before = _thread_columns(conn)
            tables_before = _table_names(conn)

            for param in INJECTION_PAYLOADS:
                payload = param.values[0]
                insert_thread_record(conn, payload, payload)

            assert _thread_columns(conn) == columns_before
            assert _table_names(conn) == tables_before

    def test_no_extra_or_missing_rows_from_stacked_statement_attempts(self):
        """Specifically targets payloads that try to DELETE/DROP via a second
        statement -- verifies row count only ever increases by exactly the
        number of legitimate inserts we performed."""
        stacked_payloads = [
            "1; DELETE FROM thread; --",
            "'); DROP TABLE thread; --",
            "'; ATTACH DATABASE '/tmp/pwn.db' AS pwn; --",
        ]
        with sqlite3.connect(DB) as conn:
            count_before = _thread_row_count(conn)

            for payload in stacked_payloads:
                insert_thread_record(conn, payload, "response")

            assert _thread_row_count(conn) == count_before + len(stacked_payloads)

    def test_null_byte_and_control_characters_round_trip_intact(self):
        payload = "abc\x00def\ndef\tghi"
        with sqlite3.connect(DB) as conn:
            insert_thread_record(conn, payload, "response")
            stored = conn.execute(
                "SELECT query FROM thread WHERE query = ?", (payload,)
            ).fetchone()
            assert stored == (payload,), "control characters were truncated or mangled"

    def test_second_order_injection_via_stored_value_reuse(self):
        """
        Second-order injection: a payload that is SAFE on insert (correctly
        parameterized) can still be dangerous if the app later reads it back
        out of the DB and splices it into a NEW query unsafely (e.g. a
        'search my history' or 'export similar prompts' feature).

        This app's insert path is fine in isolation; the real risk shows up
        the moment stored data is reused to build SQL elsewhere. This test
        documents that expectation so it's re-verified if such a feature is
        added. If the app has no such read-then-rebuild-SQL feature today,
        this test is a guardrail against introducing one unsafely later.
        """
        payload = "' OR '1'='1"
        with sqlite3.connect(DB) as conn:
            insert_thread_record(conn, payload, "response")
            fetched_query = conn.execute(
                "SELECT query FROM thread WHERE response = 'response'"
            ).fetchone()[0]

            # Simulates a hypothetical feature that re-queries using the
            # stored value. If the app ever does this with string formatting
            # instead of binding, this assertion is where it would surface.
            safe_lookup = conn.execute(
                "SELECT COUNT(*) FROM thread WHERE query = ?", (fetched_query,)
            ).fetchone()[0]
            assert safe_lookup == 1


class TestReportOutputEscaping:    
    def test_script_tag_in_response_is_escaped_in_generated_html(self):
        malicious_response = "<script>alert('xss')</script>"
        db.insert("Answer in under 10 words -- harmless prompt", malicious_response)

        report()

        with open("./reports/ai-report-clean.html") as f:
            html = f.read()

        assert "<script>alert('xss')</script>" not in html, (
            "report() writes the Gemma response into HTML with no escaping. "
            "A response containing a <script> tag is rendered live in the "
            "generated report -- this is a real stored-XSS vulnerability, "
            "not a hypothetical one. Fix: html.escape() every field written "
            "into the <td> cells in report()."
        )

    def test_prefix_stripping_removes_every_occurrence_not_just_the_injected_one(self):
        prefix = "Answer in under 10 words -- "
        stored_query = f"{prefix}Please explain, {prefix}and be concise"
        db.insert(stored_query, "some response")
        report()

        with open("./reports/ai-report-clean.html") as f:
            html = f.read()

        assert prefix not in html  # confirms .replace() strips both instances
        assert "Please explain, and be concise" in html, (
            "Only the leading injected prefix should disappear; a second "
            "occurrence that happened to be part of the user's own prompt "
            "was also silently removed, splicing the surrounding text "
            "together. This is a real display-corruption risk if a user's "
            "prompt ever legitimately contains this substring."
        )

    pytest.mark.skip(reason="Demonstration of a vulnerable implementation, not a real regression test.")

    @staticmethod
    def _vulnerable_insert(conn, query, response):
        conn.executescript(
            f"INSERT INTO thread(query, response) VALUES ('{query}', '{response}');"
        )

    def test_vulnerable_insert_is_actually_exploitable(self):
        with sqlite3.connect(DB) as conn:
            with pytest.raises(sqlite3.OperationalError):
                # DROP TABLE via stacked statement succeeds with executescript(),
                # which is exactly the class of bug these tests exist to catch.
                self._vulnerable_insert(conn, "'); DROP TABLE thread; --", "x")
                conn.execute("SELECT * FROM thread")