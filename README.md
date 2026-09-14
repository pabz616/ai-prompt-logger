# ai-prompt-logger

Leverage AI to log user prompts, limiting responses to 10 characters

## HOW IT WORkS

1. Run the `sql-report.py` script.
2. At the prompt, HOW CAN I HELP? enter your desired prompt.
3. The AI - using Gemma4 - responds in about 10 characters or less.
4. The exchanged is tracked in the database using SQLite3.

## HOW IT LOOKS
<img width="742" height="294" alt="Screenshot 2026-09-13 at 10 16 48 PM" src="https://github.com/user-attachments/assets/faa9ebd3-6f65-4506-b3af-445953350624" />


## HOW IT WAS TESTED

The script was tested for the following:

1. Successful DB connection
2. The interaction (records) are successfully stored in the DB
3. Performance test for bulk submissions (isolated db)
4. Operational error for locked database (chaos test)
5. Failed transactions can be rolled back (isolated db)
6. Corrupt DB is rejected (chaos test)
7. SQL injection payload does not impact database (isolated test)
8. Tested the prompts are in the database
9. Tested the responses are in the database and adhere to the word limit
10. Tested the timestamp is added to each record and adheres to ISO 8601 format
