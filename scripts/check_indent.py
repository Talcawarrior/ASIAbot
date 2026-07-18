with open("data_pipeline/unified_datastore.py", "r") as f:
    content = f.read()
lines = content.split("\n")
for i, line in enumerate(lines[810:820], 811):
    print(f"{i}: len={len(line)}, starts with space={line.startswith(' ')}, first chars={repr(line[:10])}")
