with open('main.py', 'rb') as f:
    content = f.read()

# Find the exact position
search_bytes = b'# Import app, state, and loop functions from split modules.\r\nfrom api import app, scan_and_bet_loop, settlement_loop, state  # noqa: E402\r\n\r\nlogger = __import__("logging").getLogger(__name__)\r\n\r\n\r\n# \xe2\x94\x80\xe2\x94\x80\xe2\x94\x80 Port conflict prevention'
idx = content.find(search_bytes)
if idx >= 0:
    print(f'Found at {idx}')
    # Print 300 bytes from there
    print(content[idx:idx+300])
else:
    print('Not found')
