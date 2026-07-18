with open("data_pipeline/unified_datastore.py", "r", encoding="utf-8") as f:
    source = f.read()

# Test a simple class
test_source = '''
class Test:
    def summary(self) -> dict[str, int]:
        """Row counts for each unified table."""
        return {
            "markets": 1,
        }
'''
compile(test_source, "<test>", "exec")
print("Test compiles OK")

# Now try the actual file
try:
    compile(source, "unified_datastore.py", "exec")
    print("Full file compiles OK")
except IndentationError as e:
    print(f"IndentationError at line {e.lineno}: {e.msg}")
    lines = source.split("\n")
    if e.lineno <= len(lines):
        print(f"Line {e.lineno}: {repr(lines[e.lineno - 1])}")
