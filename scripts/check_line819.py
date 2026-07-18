with open('data_pipeline/unified_datastore.py', 'rb') as f:
    content = f.read()
lines = content.split(b'\n')
line = lines[818]  # 0-indexed
print(f'Line 819 bytes: {line!r}')
print(f'Length: {len(line)}')
for i, b in enumerate(line):
    print(f'  [{i}] = {b} ({chr(b) if 32 <= b < 127 else "?"})')