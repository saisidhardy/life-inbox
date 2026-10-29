import http.cookiejar
import json
import urllib.request

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

BASE = "https://life-inbox.onrender.com"

# 1. Dev Login
print("[1] Logging in as siddu@gmail.com...")
login_data = json.dumps({"email": "siddu@gmail.com", "display_name": "siddu"}).encode("utf-8")
req = urllib.request.Request(f"{BASE}/api/auth/dev-login", data=login_data, headers={"Content-Type": "application/json"})
user = json.loads(opener.open(req).read().decode())
print(f"    Logged in user: {user['display_name']} (User ID: {user['id']})")

# 2. Add sample notes
sample_notes = [
    "Meeting with Sarah & Mark about Q4 mobile redesign roadmap. We agreed to prioritize the iOS checkout overhaul. Need to send updated pitch deck to Alex by Friday. Mark will review analytics next week.",
    "Q3 estimated tax payment is due on September 15. Must log into IRS EFTPS and pay $3,200. Important to keep the confirmation receipt for CPA.",
    "Schedule annual dental cleaning with Dr. Harris. Recommended to get wisdom teeth x-ray done before November. Pick up allergy medication from CVS today.",
    "Hardware store run: 2-inch wood screws, sandpaper grit 120, painter's tape, cordless drill bits.",
    "Idea: Micro-SaaS that monitors Stripe webhooks and sends instant WhatsApp alerts for failed enterprise payments. Could charge $29/mo."
]

print("\n[2] Creating 5 test notes in Siddu's inbox...")
created_items = []
for idx, text in enumerate(sample_notes, 1):
    payload = json.dumps({"raw_text": text}).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/api/items", data=payload, headers={"Content-Type": "application/json"})
    item = json.loads(opener.open(req).read().decode())
    created_items.append(item)
    print(f"    Created Note #{item['id']}: {item.get('raw_text', '')[:65]}...")

# 3. Trigger AI organization
print("\n[3] Triggering AI Organization (/api/analyze)...")
req_analyze = urllib.request.Request(f"{BASE}/api/analyze", data=b"{}", headers={"Content-Type": "application/json"})
try:
    analysis_resp = json.loads(opener.open(req_analyze).read().decode())
    print("    AI Organization complete!")
    print(f"    Analysis Run ID: {analysis_resp.get('id', 'N/A')}")
except Exception as e:
    print(f"    Analyze response: {e}")

# 4. Check tasks
print("\n[4] Fetching Extracted Tasks (/api/tasks)...")
req_tasks = urllib.request.Request(f"{BASE}/api/tasks?status=all")
tasks = json.loads(opener.open(req_tasks).read().decode())
print(f"    Total Tasks extracted: {len(tasks)}")
for t in tasks:
    status = t.get("status", "open").upper()
    pri = t.get("priority", "Medium")
    due = t.get("due_date") or "None"
    text = t.get("text") or t.get("title", "")
    print(f"    - [{status}] {text} (Priority: {pri}, Due: {due})")

# 5. Check topics
print("\n[5] Fetching Topics (/api/topics)...")
req_topics = urllib.request.Request(f"{BASE}/api/topics")
topics = json.loads(opener.open(req_topics).read().decode())
print(f"    Total Topics: {len(topics)}")
for tp in topics:
    name = tp.get("name", "Unknown")
    count = tp.get("item_count", 0)
    print(f"    - Topic: '{name}' ({count} notes)")

# 6. Test 'Ask Your Inbox'
questions = [
    "When do I need to send the pitch deck to Alex?",
    "How much is my Q3 estimated tax payment?",
    "What do I need to pick up at the hardware store?"
]
print("\n[6] Testing 'Ask Your Inbox' (/api/ask)...")
for q in questions:
    payload = json.dumps({"question": q}).encode("utf-8")
    req_ask = urllib.request.Request(f"{BASE}/api/ask", data=payload, headers={"Content-Type": "application/json"})
    ans = json.loads(opener.open(req_ask).read().decode())
    print(f"\n    Q: \"{q}\"")
    print(f"    A: {ans.get('answer', ans)}")
    citations = ans.get("citations", [])
    if citations:
        print(f"       Citations: {citations}")
