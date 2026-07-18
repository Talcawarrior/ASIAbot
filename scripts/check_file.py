with open('data_pipeline/unified_datastore.py', 'rb') as f:
    content = f.read()

# Check first few bytes for BOM
print(f'First 10 bytes: {content[:10]!r}')

# Check for any non-ASCII bytes in the first 1000 bytes
for i, b in enumerate(content[:1000]):
    if b > 127:
        print(f'Non-ASCII at {i}: {b} ({chr(b) if b < 256 else "?"})')

# Check lines around 819
lines = content.split(b'\n')
for i, line in enumerate(lines[815:825], 816):
    print(f'{i}: {line!r}')