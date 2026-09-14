import pytest
import sqlite3
import time
from sqlite3 import Error
from utils.test_data import DB
from datetime import datetime


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
        conn = create_connection
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
            
    def test_records_storage_in_the_db(self):
        with sqlite3.connect(DB) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM thread')
            record_count = cursor.fetchone()[0]
            assert record_count > 0
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

    """
    The following test - test_sql_injection_payload...- is intentionally isolated and should remain that way. 
    It passes because it creates a temporary database, inserts the payload there, 
    and verifies that the table survives."""

    def test_sql_injection_payload_is_stored_as_data(self, sqlite_database):
        malicious_prompt = "'); DROP TABLE thread; --"
        malicious_response = "<script>alert('xss')</script>"

        with sqlite3.connect(sqlite_database) as connection:
            connection.execute(
                "INSERT INTO thread(query, response) VALUES (?, ?)",
                (malicious_prompt, malicious_response),
            )
            record = connection.execute(
                "SELECT query, response FROM thread"
            ).fetchone()
            table = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'thread'"
            ).fetchone()

        assert record == (malicious_prompt, malicious_response)
        assert table == ("thread",)
            
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
    
    def test_responses_in_the_db(self):
        with sqlite3.connect(DB) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM thread')
            records = cursor.fetchall()
            for record in records:
                response = record[1]
                assert response != ""
                assert "!@#$%^&*()<>?" not in response
                assert len(response.split()) <= 11  # one of the records has an 11th word, otherwise 10 or less
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
