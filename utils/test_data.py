"URL to connect to the test data server"
'https://ollama.com/connect?key=c3NoLWVkMjU1MTkgQUFBQUMzTnphQzFsWkRJMU5URTVBQUFBSUFTYUkrVEZMSk93THhteVBMbnlwd1ZabjZ5VW5vV0JWQVRPWVZCSlFyc1I&name=MacBookPro'

DB = "ai-class.db"
MODEL = 'gemma4'
HTML_START = '<!DOCTYPE html>\n<html>\n<head><link rel="stylesheet" href="styles.css"></head><body><table>\n'
HTML_TITLE = '<h1>GEMMA4 PROMPT LOGS</h1>\n'
HTML_TABLE_HEADER = '<tr class="header">\n<td>PROMPT</td>\n<td>RESPONSE</td>\n<td>TIMESTAMP</td>\n</tr>\n'
HTML_END = '\n</table>\n</body>\n</html>'