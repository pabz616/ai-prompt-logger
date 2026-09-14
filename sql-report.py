from ollama import chat, ChatResponse
import sqlite3
from utils.test_data import MODEL, HTML_START, HTML_TABLE_HEADER, HTML_END, HTML_TITLE, DB

injection = 'Answer in under 10 words'


# CREATE THE TABLE IF IT DOES NOT EXIST
class db:
    def create():
        conn = sqlite3.connect("ai-class.db")
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS thread (query,response,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        """)
        conn.commit()
        conn.close()

# ADD A NEW RECORD TO THE TABLE
    def insert(query, response):
        conn = sqlite3.connect("ai-class.db")
        cursor = conn.cursor()
        sql = 'insert into thread(query,response) values(?,?)'
        cursor.execute(sql, (query, response))
        conn.commit()
        conn.close()

# SELECT RECORD FROM THE TABLE
    def select():
        conn = sqlite3.connect(DB)
        cursor = conn.cursor()
        sql = 'select * from thread'
        cursor.execute(sql)
        result = cursor.fetchall()
        conn.close()
        return result


# GENERATE THE REPORT
def report():
    response = db.select()
    with open('./reports/ai-report-clean.html', 'w') as file:
        file.write(HTML_START+HTML_TITLE+HTML_TABLE_HEADER)
        for line in response:
            request = line[0].replace('Answer in under 10 words -- ', '')
            file.write(f'''
            <tr>
            <td>{request}</td>
            <td>{line[1]}</td>
            <td>{line[2]}</td>
            </tr>
            ''')
        file.write(HTML_END)


# RUN THE SCRIPT
def ai(query):
    response: ChatResponse = chat(model=MODEL, messages=[{'role': 'user', 'content': query, },])
    return response.message.content


def main():
    db.create()

    while True:
        query = input('How Can I Help: ')
        query = f'{injection} -- {query}'
        response = ai(query)
        db.insert(query, response)
        report()
        print(query)
        print(response)
        print('=' * 70)


if __name__ == "__main__":
    main()
