with open("data_pipeline/unified_datastore.py", "rb") as f:
    content = f.read()
lines = content.split(b"\n")
for i in [816, 817, 818, 819]:
    line = lines[i - 1]
    print(f"Line {i}: len={len(line)}, bytes={line!r}")
    for j, b in enumerate(line):
        if b < 32 or b > 126:
            print(f"  Non-printable at pos {j}: {b} ({chr(b) if b < 256 else '?'})")
