from ollama import chat, ChatResponse
from utils.test_data import MODEL


def ai(query):
    response: ChatResponse = chat(model=MODEL, messages=[{
        'role': 'user',
        'content': query,
    },])
    
    return response.message.content


while True:
    query = input('How Can I Help: ')
    response = ai(query)
    print(query)
    print(response)
    print('-----')