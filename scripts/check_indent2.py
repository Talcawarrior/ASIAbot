with open('data_pipeline/unified_datastore.py', 'r') as f:
    lines = f.readlines()
for i, line in enumerate(lines[815:825], 816):
    leading = len(line) - len(line.lstrip())
    print(f'{i}: leading={leading}, starts_with_space={line.startswith(" ")}, first_chars={repr(line[:10])}')