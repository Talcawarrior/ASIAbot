# Check the build_counterfactual_dataset function for issues
with open("data_pipeline/unified_datastore.py", "r") as f:
    lines = f.readlines()

# Find the build_counterfactual_dataset function
for i, line in enumerate(lines):
    if "def build_counterfactual_dataset" in line:
        print(f"Found at line {i + 1}: {repr(line)}")
        # Print from function start to end
        for j in range(i, min(len(lines), i + 200)):
            if lines[j].strip() and not lines[j].startswith(" ") and not lines[j].startswith("\t") and j > i:
                # Next top-level definition
                print(f"Function ends around line {j + 1}")
                break
            print(f"{j + 1}: {repr(lines[j])}")
        break
