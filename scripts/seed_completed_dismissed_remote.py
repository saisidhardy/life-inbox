import http.cookiejar
import json
import urllib.request

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
BASE = "https://life-inbox.onrender.com"

# 1. Login as siddu
login_data = json.dumps({"email": "siddu@gmail.com", "display_name": "siddu"}).encode("utf-8")
req = urllib.request.Request(f"{BASE}/api/auth/dev-login", data=login_data, headers={"Content-Type": "application/json"})
opener.open(req)

# 2. Add sample notes
notes_to_add = [
    "Sprint retrospective: Shipped the iOS checkout update to production on Thursday. Follow up with analytics team next sprint for conversion lift metrics.",
    "DevOps cleanup note: Decided to dismiss legacy Docker compose v1 migration because compose v1 is officially deprecated and obsolete."
]

for n in notes_to_add:
    req = urllib.request.Request(f"{BASE}/api/items", data=json.dumps({"raw_text": n}).encode("utf-8"), headers={"Content-Type": "application/json"})
    opener.open(req)

# 3. Analyze
try:
    opener.open(urllib.request.Request(f"{BASE}/api/analyze", data=b"{}", headers={"Content-Type": "application/json"}))
except Exception as exc:
    print("Analyze response:", exc)

# 4. Fetch all tasks
all_tasks = json.loads(opener.open(urllib.request.Request(f"{BASE}/api/tasks?status=all")).read().decode())
print(f"Total tasks on remote: {len(all_tasks)}")

for t in all_tasks:
    t_id = t["id"]
    text = t["text"].lower()
    if any(k in text for k in ["shipped", "pitch deck", "allergy medication", "follow up"]) and t["status"] == "open":
        print(f"Completing #{t_id}: {t['text']}")
        opener.open(urllib.request.Request(f"{BASE}/api/tasks/{t_id}/complete", data=b""))
    elif any(k in text for k in ["docker", "legacy", "compose", "tax payment"]) and t["status"] == "open":
        print(f"Dismissing #{t_id}: {t['text']}")
        opener.open(urllib.request.Request(f"{BASE}/api/tasks/{t_id}/dismiss", data=b""))

print("\n--- Current Remote Task Status Summary ---")
for st in ["open", "completed", "dismissed"]:
    ts = json.loads(opener.open(urllib.request.Request(f"{BASE}/api/tasks?status={st}")).read().decode())
    print(f"  {st.upper()}: {len(ts)} tasks")
    for task in ts:
        print(f"    - [{st.upper()}] {task['text']} ({task.get('priority', 'Medium')})")
