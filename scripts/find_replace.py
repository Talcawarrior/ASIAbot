with open("main.py", "rb") as f:
    content = f.read()

# Find the exact bytes we want to replace
search = b'logger = __import__("logging").getLogger(__name__)\r\n\r\n\r\n# \xe2\x94\x80\xe2\x94\x80\xe2\x94\x80 Port conflict prevention'
idx = content.find(search)
if idx >= 0:
    print(f"Found at {idx}")
    print(content[idx : idx + 100])
else:
    print("Not found")
