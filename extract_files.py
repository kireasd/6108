import json
import os

log_path = r'C:\Users\PC\.gemini\antigravity\brain\cdcc6215-dac6-457b-9d31-09f593053390\.system_generated\logs\overview.txt'

files = {'index.html': None, 'style.css': None, 'script.js': None}

with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        if 'write_to_file' in line or 'replace_file_content' in line:
            start = line.find('{')
            if start != -1:
                try:
                    data = json.loads(line[start:])
                    for call in data.get('tool_calls', []):
                        if call['name'] in ['write_to_file', 'replace_file_content']:
                            args = call.get('args', {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except:
                                    continue
                            
                            target = args.get('TargetFile', '')
                            content = args.get('CodeContent')
                            if not content:
                                content = args.get('ReplacementContent')
                                
                            for k in files.keys():
                                if k in target and content:
                                    files[k] = content
                except Exception as e:
                    pass

for k, v in files.items():
    if v:
        # if v is double-encoded JSON string, it might start with quote
        if v.startswith('"') and v.endswith('"') and '\\n' in v:
            try:
                v = json.loads(v)
            except:
                v = v[1:-1].replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
        
        with open(k, 'w', encoding='utf-8') as f:
            f.write(v)
        print(f'Saved {k}, length: {len(v)}')
