# Test script to isolate the issue
with open("data_pipeline/unified_datastore.py", "r") as f:
    lines = f.readlines()

# Find the summary method
for i, line in enumerate(lines):
    if "def summary" in line:
        print(f"Found at line {i + 1}: {repr(line)}")
        # Print context
        for j in range(max(0, i - 5), min(len(lines), i + 10)):
            print(f"{j + 1}: {repr(lines[j])}")
        break
