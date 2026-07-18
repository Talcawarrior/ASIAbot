with open("data_pipeline/unified_datastore.py", "rb") as f:
    content = f.read()

# Keep only ASCII characters (0-127) and newlines
cleaned = bytearray()
for b in content:
    if b <= 127 or b in (10, 13):  # ASCII + LF + CR
        cleaned.append(b)
    else:
        cleaned.append(ord("?"))  # Replace non-ASCII with ?

# Normalize line endings to LF only
cleaned = cleaned.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

with open("data_pipeline/unified_datastore.py", "wb") as f:
    f.write(cleaned)

print("Cleaned file written")
