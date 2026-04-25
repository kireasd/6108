import json

log_path = r'C:\Users\PC\.gemini\antigravity\brain\cdcc6215-dac6-457b-9d31-09f593053390\.system_generated\logs\overview.txt'

with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

# Line 284 is index 283
line = lines[283]
start = line.find('{')
data = json.loads(line[start:])

files = {}
for call in data.get('tool_calls', []):
    if call['name'] == 'write_to_file':
        args = call.get('args', {})
        if isinstance(args, str):
            args = json.loads(args)
        
        target = args.get('TargetFile', '')
        content = args.get('CodeContent', '')
        
        # content is a double encoded JSON string
        if content.startswith('"') and content.endswith('"'):
            content = json.loads(content)
            
        if 'index.html' in target:
            files['index.html_V3'] = content
        elif 'style.css' in target:
            files['style.css_V3'] = content
        elif 'script.js' in target:
            files['script.js_V3'] = content
        elif 'main.py' in target:
            files['main.py_V3'] = content

for k, v in files.items():
    with open(k, 'w', encoding='utf-8') as f:
        f.write(v)
    print(f'Saved {k}, length: {len(v)}')
