import ast

for file in ['index.html', 'style.css', 'script.js']:
    try:
        with open(file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # The content has literally a single quote or double quote wrapping it and \n inside it
        # Actually it's something like "<!DOCTYPE html>\n<html..." with truncated 6098 bytes.
        # Wait! In the previous command, ast.literal_eval failed because it said:
        # SyntaxError: unterminated string literal
        # This implies the file itself was truncated!
        pass
