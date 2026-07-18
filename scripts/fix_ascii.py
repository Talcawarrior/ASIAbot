with open('data_pipeline/unified_datastore.py', 'rb') as f:
    content = f.read()

# Replace common non-ASCII characters
content = content.replace(b'\xe2\x80\x94', b'--')  # em dash
content = content.replace(b'\xe2\x80\x93', b'-')   # en dash
content = content.replace(b'\xe2\x80\x99', b"'")  # right single quote
content = content.replace(b'\xe2\x80\x98', b"'")  # left single quote
content = content.replace(b'\xe2\x80\x9c', b'"')  # left double quote
content = content.replace(b'\xe2\x80\x9d', b'"')  # right double quote
content = content.replace(b'\xe2\x80\xa6', b'...')  # ellipsis
content = content.replace(b'\xc2\xa0', b' ')        # non-breaking space

with open('data_pipeline/unified_datastore.py', 'wb') as f:
    f.write(content)

print('Replaced non-ASCII characters')