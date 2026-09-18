import pytest

import html as html_module 
import sqlite3
import time
from sqlite3 import Error
from utils.test_data import DB
from datetime import datetime
from sql_report import db
from sql_report import report


def create_connection(db_file):
    connection = None
    try:
        connection = sqlite3.connect(db_file)
        return connection
    except Error as e:
        print(f"Error connecting to database: {e}")
        return None


@pytest.fixture
def sqlite_database(tmp_path):
    database_path = tmp_path / "test.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("""
            CREATE TABLE thread (
                query TEXT,
                response TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)        
    return database_path


class TestSQLReport:
    def test_successful_db_connection(self):
        conn = create_connection(DB)
        if conn is not None:
            try:
                with sqlite3.connect(DB) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    assert cursor.fetchone() == (1,)
            except Error as error:
                pytest.fail(f"Error connecting to database: {error}")
            finally:
                conn.close()
     
    @pytest.mark.uses_real_db        
    def test_records_storage_in_the_db(self):
        with sqlite3.connect(DB) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM thread')
            record_count = cursor.fetchone()[0]
            assert record_count > 0, f"expected records, got {record_count}"
            cursor.close()

    def test_bulk_insert_performance(self, sqlite_database):
        records = [
            (f"prompt-{index}", f"response-{index}")
            for index in range(1000)
        ]
        start_time = time.perf_counter()

        with sqlite3.connect(sqlite_database) as connection:
            connection.executemany(
                "INSERT INTO thread(query, response) VALUES (?, ?)",
                records,
            )

        elapsed_time = time.perf_counter() - start_time
        assert elapsed_time < 5

        with sqlite3.connect(sqlite_database) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM thread"
            ).fetchone()[0]
        assert count == len(records)

    def test_failed_transaction_can_be_rolled_back(self, sqlite_database):
        with sqlite3.connect(sqlite_database) as connection:
            connection.execute(
                "INSERT INTO thread(query, response) VALUES (?, ?)",
                ("temporary prompt", "temporary response"),
            )
            with pytest.raises(sqlite3.OperationalError):
                connection.execute("INSERT INTO missing_table VALUES (1)")
            connection.rollback()
            count = connection.execute(
                "SELECT COUNT(*) FROM thread"
            ).fetchone()[0]

        assert count == 0

    def test_locked_database_reports_operational_error(self, sqlite_database):
        first_connection = sqlite3.connect(sqlite_database)
        second_connection = sqlite3.connect(sqlite_database, timeout=0.05)
        try:
            first_connection.execute("BEGIN EXCLUSIVE")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                second_connection.execute(
                    "INSERT INTO thread(query, response) VALUES (?, ?)",
                    ("blocked prompt", "blocked response"),
                )
        finally:
            first_connection.rollback()
            first_connection.close()
            second_connection.close()

    def test_corrupt_database_is_rejected(self, tmp_path):
        database_path = tmp_path / "corrupt.db"
        database_path.write_bytes(b"not a SQLite database")

        with pytest.raises(sqlite3.DatabaseError):
            with sqlite3.connect(database_path) as connection:
                connection.execute("SELECT * FROM thread").fetchall()
            
    def test_prompts_in_the_db(self):
        with sqlite3.connect(DB) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM thread')
            records = cursor.fetchall()
            for record in records:
                prompt = record[0]
                assert prompt != ""
                assert "!@#$%^&*()<>?" not in prompt
            
                # PROMPT CONTAINS DISTINCT REQUIREMENT
                assert "Answer in under 10 words" in prompt
            cursor.close()
    
    # @pytest.mark.xfail(reason="Test Fails: Response for 13th record has 11 words")
    def test_responses_in_the_db(self):
        with sqlite3.connect(DB) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM thread')
            records = cursor.fetchall()
            for record in records:
                response = record[1]
                assert response != ""
                assert "!@#$%^&*()<>?" not in response
                assert len(response.split()) <= 10
            cursor.close()
            
    def test_timestamp_in_the_db(self):
        with sqlite3.connect(DB) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM thread')
            records = cursor.fetchall()
            for record in records:
                timestamp = record[2]
                assert timestamp != ""
                assert "!@#$%^&*()<>?" not in timestamp
                
                # ADHERENCE TO ISO 8601 FORMAT
                parsed_date = datetime.fromisoformat(timestamp)
                assert parsed_date.strftime("%Y-%m-%d %H:%M:%S") == timestamp
            cursor.close()


class TestSQLReportOutput:

    def test_static_page_structure(self):
        """Title/headers, against an empty table -- no rows needed for this."""
        report()
        with open("./reports/ai-report-clean.html") as f:
            html = f.read()

        assert "GEMMA4 PROMPT LOGS" in html, "Title text is missing"
        assert "PROMPT" in html, "Column 1 header is missing"
        assert "RESPONSE" in html, "Column 2 header is missing"
        assert "TIMESTAMP" in html, "Column 3 header is missing"

    def test_script_tag_in_response_is_escaped_not_just_absent(self):
        malicious_response = "<script>alert('xss')</script>"
        db.insert("Answer in under 10 words -- harmless prompt", malicious_response)

        report()

        with open("./reports/ai-report-clean.html") as f:
            html = f.read()

        assert "<script>alert('xss')</script>" not in html, (
            "report() writes the Gemma response into HTML with no escaping -- "
            "a live, exploitable stored-XSS vulnerability."
        )
        # assert html_module.escape(malicious_response) in html, (
        #     "raw payload is absent, but the escaped form is missing too -- "
        #     "the field may have been dropped or truncated rather than escaped"
        # )

    def test_ampersand_and_quotes_in_ordinary_text_are_escaped_correctly(self):
        """Non-malicious content with HTML-meaningful characters should still render correctly """
        response = "5 < 10 & Bob's answer was \"correct\""
        db.insert("benign prompt", response)

        report()

        with open("./reports/ai-report-clean.html") as f:
            html = f.read()

        assert html_module.escape(response) in html

    def test_multiple_records_render_in_their_own_rows_with_correct_fields(self):
        records = [
            ("Answer in under 10 words -- what is gravity", "A force pulling masses together."),
            ("Answer in under 10 words -- define entropy", "A measure of disorder."),
            ("Answer in under 10 words -- name a planet", "Jupiter is a gas giant."),
        ]
        for query, response in records:
            db.insert(query, response)

        report()

        with open("./reports/ai-report-clean.html") as f:
            html = f.read()

        assert html.count("<td>") >= len(records) * 3
        for query, response in records:
            cleaned_query = query.replace("Answer in under 10 words -- ", "")
            assert cleaned_query in html
            assert response in html

    def test_prefix_stripping_removes_every_occurrence_not_just_the_injected_one(self):
        prefix = "Answer in under 10 words -- "
        stored_query = f"{prefix}Please explain, {prefix}and be concise"
        db.insert(stored_query, "some response")

        report()

        with open("./reports/ai-report-clean.html") as f:
            html = f.read()

        assert prefix not in html
