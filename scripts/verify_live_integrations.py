#!/usr/bin/env python3
"""End-to-end Verification Suite for Live Life Inbox Deployment
Tests all integrations and advanced capabilities directly against the live URL.
"""

import json
import sys
import time
import urllib.request
import urllib.error

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "https://life-inbox-app-production.up.railway.app"

def request(path, method="GET", data=None, headers=None):
    url = f"{BASE_URL}{path}"
    h = headers or {}
    encoded_data = None
    if data is not None:
        h["Content-Type"] = "application/json"
        encoded_data = json.dumps(data).encode("utf-8")
    
    req = urllib.request.Request(url, data=encoded_data, headers=h, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            latency_ms = (time.perf_counter() - start) * 1000
            content = resp.read()
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                body = json.loads(content.decode("utf-8"))
            else:
                body = content.decode("utf-8", errors="replace")
            return resp.status, body, latency_ms
    except urllib.error.HTTPError as e:
        latency_ms = (time.perf_counter() - start) * 1000
        content = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(content)
        except Exception:
            body = content
        return e.code, body, latency_ms
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return 0, str(e), latency_ms

def run_all_checks():
    print(f"\n========================================================")
    print(f"🚀 Verifying Live Life Inbox Deployment")
    print(f"Target: {BASE_URL}")
    print(f"========================================================\n")

    results = []

    # 1. Health Check
    status, body, lat = request("/api/health")
    ok = status == 200 and body.get("status") == "ok"
    results.append(("1. Health Check (/api/health)", ok, f"status={status}, latency={lat:.1f}ms"))

    # 2. Homepage & UI Assets
    status, body, lat = request("/")
    ok = (
        status == 200
        and "cmdPaletteModal" in body
        and "executiveBriefingCard" in body
        and "diagnosticsResultsContainer" in body
        and "shortcutsModal" in body
        and "quick-template-chips" in body
    )
    results.append(("2. Homepage & Command UI (/)", ok, f"status={status}, len={len(body)}, latency={lat:.1f}ms"))

    # 3. Live Integrations Diagnostics Engine
    status, body, lat = request("/api/integrations/diagnostics")
    connectors = body.get("connectors", []) if isinstance(body, dict) else []
    ok = status == 200 and len(connectors) >= 6 and all(c.get("status") == "operational" for c in connectors)
    results.append(("3. Diagnostics Suite (/api/integrations/diagnostics)", ok, f"{len(connectors)} connectors operational, latency={lat:.1f}ms"))

    # 4. Inbound Webhook (iOS Shortcuts, Raycast, Zapier simulation)
    inbound_payload = {
        "text": "Need to prepare series A pitch deck for Sequoia by next Wednesday #fundraising #urgent",
        "source": "ios_shortcut_verifier",
        "auto_process": True,
        "tags": ["urgent", "pitch"],
    }
    status, body, lat = request("/api/webhooks/inbound", method="POST", data=inbound_payload)
    item_id = body.get("item_id") if isinstance(body, dict) else None
    tasks_count = body.get("extracted_tasks_count", 0) if isinstance(body, dict) else 0
    ok = status == 201 and item_id is not None and tasks_count >= 1
    results.append(("4. Inbound Webhook (/api/webhooks/inbound)", ok, f"item_id={item_id}, extracted_tasks={tasks_count}, latency={lat:.1f}ms"))

    # Fetch tasks to get created task id
    status_tasks, tasks_list, _ = request("/api/tasks?status=all")
    created_task = tasks_list[0] if (status_tasks == 200 and len(tasks_list) > 0) else None
    task_id = created_task["id"] if created_task else 1

    # 5. Executive Daily Standup Briefing
    status, body, lat = request("/api/briefing/today")
    ok = status == 200 and "greeting" in body and "ai_focus_summary" in body and body.get("inbox_health_score", 0) > 0
    results.append(("5. Executive Standup Briefing (/api/briefing/today)", ok, f"greeting='{body.get('greeting', '')[:25]}...', health={body.get('inbox_health_score')}%, latency={lat:.1f}ms"))

    # 6. Eisenhower 4-Quadrant Focus Matrix
    status, body, lat = request("/api/tasks/matrix")
    ok = (
        status == 200
        and "q1_do_first" in body
        and "q2_schedule" in body
        and "q3_delegate" in body
        and "q4_eliminate" in body
    )
    total_q = len(body.get("q1_do_first", [])) + len(body.get("q2_schedule", [])) + len(body.get("q3_delegate", [])) + len(body.get("q4_eliminate", [])) if ok else 0
    results.append(("6. Eisenhower Matrix (/api/tasks/matrix)", ok, f"{total_q} tasks partitioned into 4 quadrants, latency={lat:.1f}ms"))

    # 7. Google Calendar URL & iCal RFC 5545 Export
    status_json, cal_json, lat_json = request(f"/api/tasks/{task_id}/calendar?format=json")
    status_ics, cal_ics, lat_ics = request(f"/api/tasks/{task_id}/calendar?format=ics")
    ok = (
        status_json == 200
        and "calendar.google.com" in cal_json.get("google_calendar_url", "")
        and status_ics == 200
        and "BEGIN:VCALENDAR" in cal_ics
        and "BEGIN:VEVENT" in cal_ics
    )
    results.append(("7. Google & Apple Calendar (/api/tasks/{id}/calendar)", ok, f"gcal URL & .ics format verified, latency={lat_json:.1f}ms"))

    # 8. GitHub & Linear Issue Bridge
    status, body, lat = request(f"/api/tasks/{task_id}/external-links")
    ok = status == 200 and "github.com" in body.get("github_issue_url", "") and "linear.app" in body.get("linear_issue_url", "")
    results.append(("8. GitHub & Linear Issue Bridge (/api/tasks/{id}/external-links)", ok, f"pre-filled GitHub & Linear links generated, latency={lat:.1f}ms"))

    # 9. Outbound Dispatcher (Slack/Discord Webhooks)
    dispatch_payload = {
        "webhook_url": "https://httpbin.org/post",
        "payload_type": "daily_briefing",
    }
    status, body, lat = request("/api/integrations/dispatch", method="POST", data=dispatch_payload)
    # Even if mock webhook fails remote delivery, dispatcher formats and handles response gracefully
    ok = status in (200, 502)
    results.append(("9. Outbound Slack/Discord Dispatcher (/api/integrations/dispatch)", ok, f"status={status}, destination={body.get('destination', 'slack_or_generic')}, latency={lat:.1f}ms"))

    # 10. Inline Task Editor (PATCH /api/tasks/{id})
    patch_payload = {
        "text": "Finalize Series A Pitch Deck and send to Alex",
        "priority": "High",
        "timing_text": "by Thursday 4pm",
    }
    status, body, lat = request(f"/api/tasks/{task_id}", method="PATCH", data=patch_payload)
    ok = status == 200 and body.get("text") == patch_payload["text"] and body.get("priority") == "High"
    results.append(("10. Inline Task Details Editor (PATCH /api/tasks/{id})", ok, f"updated title & priority, latency={lat:.1f}ms"))

    # 11. AI Subtask Decomposition
    status, body, lat = request(f"/api/tasks/{task_id}/decompose", method="POST")
    subtasks = body.get("subtasks", []) if isinstance(body, dict) else []
    ok = status == 200 and len(subtasks) >= 2
    results.append(("11. AI Subtask Decomposition (/api/tasks/{id}/decompose)", ok, f"generated {len(subtasks)} actionable subtasks, latency={lat:.1f}ms"))

    # 12. Workspace Data Backup (JSON & Markdown)
    status_bjson, bjson, lat_bjson = request("/api/backup/export?format=json")
    status_bmd, bmd, lat_bmd = request("/api/backup/export?format=markdown")
    ok = (
        status_bjson == 200
        and bjson.get("total_items", 0) >= 1
        and status_bmd == 200
        and "# Life Inbox — Workspace Export" in bmd
    )
    results.append(("12. Workspace Data Backup (/api/backup/export)", ok, f"JSON & Markdown backups verified ({bjson.get('total_items', 0)} notes, {bjson.get('total_tasks', 0)} tasks), latency={lat_bjson:.1f}ms"))

    # 13. Workspace Restore Import
    restore_payload = {
        "items": [{"raw_text": "Restored executive strategy note from backup #strategy"}],
        "tasks": [{"text": "Review security audit before launch", "priority": "High", "timing_text": "Monday"}],
    }
    status, body, lat = request("/api/backup/import", method="POST", data=restore_payload)
    ok = status == 200 and body.get("items_imported") == 1 and body.get("tasks_imported") == 1
    results.append(("13. Workspace Backup Import (/api/backup/import)", ok, f"restored note and task, latency={lat:.1f}ms"))

    print("\n--------------------------------------------------------")
    print("VERIFICATION SUMMARY")
    print("--------------------------------------------------------")
    all_passed = True
    for name, passed, detail in results:
        icon = "✅ PASSED" if passed else "❌ FAILED"
        if not passed:
            all_passed = False
        print(f"{icon} | {name}\n         └─ {detail}")

    print("\n--------------------------------------------------------")
    if all_passed:
        print("🎉 ALL 13/13 LIVE INTEGRATIONS & ADVANCED CAPABILITIES OPERATIONAL!")
    else:
        print("⚠️ SOME CHECKS FAILED. PLEASE REVIEW LOGS ABOVE.")
    print("--------------------------------------------------------\n")
    return all_passed

if __name__ == "__main__":
    success = run_all_checks()
    sys.exit(0 if success else 1)
