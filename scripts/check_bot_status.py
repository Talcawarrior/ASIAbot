import requests
import time

for i in range(3):
    r = requests.get("http://localhost:8091/api/status", timeout=10)
    data = r.json()
    print(
        f"Check {i + 1}: is_running={data.get('is_running')}, tasks={list(data.get('tasks', {}).keys())}, last_scan={data.get('stats', {}).get('last_scan')}"
    )
    time.sleep(5)
