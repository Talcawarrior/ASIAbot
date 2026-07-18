import requests
import time

for i in range(3):
    r = requests.get("http://localhost:8091/api/status", timeout=10)
    data = r.json()
    stats = data.get("stats", {})
    print(f"Check {i + 1}: last_scan={stats.get('last_scan')}, total_signals={stats.get('total_signals')}")
    time.sleep(10)
