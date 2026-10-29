# Life Inbox — 60–90 Second Demo Recording Script

This script outlines the exact storyboard, timing, and talking points for recording an executive walkthrough demo of **Life Inbox**.

---

## 🎬 Recording Setup Checklist

- [ ] **Resolution:** 1080p (1920x1080) or 1440p (2560x1440), 60 FPS.
- [ ] **Browser:** Clean browser window (Chrome/Arc) with bookmarks bar hidden. Zoom at 110% for crisp typography.
- [ ] **Environment:** Pre-loaded with `APP_TOKEN` so authentication prompt does not interrupt the flow.
- [ ] **Initial State:** 3–5 clean notes in the inbox (or follow the live typing steps below).
- [ ] **Terminal:** Split or secondary window ready with virtual environment activated.

---

## ⏱️ Storyboard & Timing (Total: 80 seconds)

### Scene 1: Frictionless Capture (0:00 – 0:15)
* **Visual:** Browser showing Life Inbox clean dashboard.
* **Action:**
  1. Click into the capture input.
  2. Paste or type rapidly:
     > `Meeting with Alex regarding Q4 redesign roadmap. Must send updated pitch deck by Friday. Review analytics next week.`
  3. Press `Ctrl + Enter` to save instantly.
* **Voiceover:**
  > *"Most notes apps force you to pick a folder, add tags, and structure tasks before you can write. With Life Inbox, capture is frictionless—jot down your messy stream of thought and press Ctrl+Enter."*

---

### Scene 2: Structured AI Auto-Processing (0:15 – 0:35)
* **Visual:** The new note appears at the top of the feed with its analysis pill.
* **Action:**
  1. Highlight the note card.
  2. Point out the category badge (`Work`), tags (`#work`, `#roadmap`), and the extracted action items:
     - `Send updated pitch deck to Alex` (Priority: **High**, Due: **Friday**)
     - `Review analytics next week` (Priority: **Medium**, Due: **next week**)
  3. Click one checkbox to demonstrate real-time completion state.
* **Voiceover:**
  > *"Behind the scenes, Life Inbox automatically parses the note into a validated Pydantic schema: identifying taxonomy, generating tags, and extracting actionable tasks with inferred priorities and deadlines."*

---

### Scene 3: "Ask Your Inbox" Grounded Retrieval (0:35 – 0:55)
* **Visual:** Scroll to the "Ask Your Inbox" card in the sidebar or top banner.
* **Action:**
  1. Type: `When do I need to send the pitch deck to Alex?`
  2. Click **Ask**.
  3. Show the response appearing in $< 200\text{ ms}$:
     > *"Based on your notes: [Note #1] ("Meeting with Alex regarding Q4 redesign roadmap..."), you need to send the updated pitch deck to Alex by Friday."*
* **Voiceover:**
  > *"Instead of digging through folders, 'Ask Your Inbox' uses an in-memory BM25 retrieval ranker to find relevant context and synthesize an answer grounded with exact citations back to the source notes."*

---

### Scene 4: Weekly Digest & AI Telemetry (0:55 – 1:15)
* **Visual:** Open the Dashboard view.
* **Action:**
  1. Point to the **Weekly AI Digest** card summarizing open tasks and stale items.
  2. Highlight the **AI Cost & Latency Telemetry** card:
     - Total Calls: `14`
     - Total Tokens: `1,280`
     - Cumulative Cost: `$0.00019`
     - Average Latency: `12.4 ms`
* **Voiceover:**
  > *"The dashboard aggregates your weekly focus and surfaces stale items. More importantly for an AI product, it instruments real-time telemetry: tracking tokens, latency percentiles, and exact dollar costs per call."*

---

### Scene 5: Evaluation Suite & Quality Gates (1:15 – 1:30)
* **Visual:** Switch to terminal window.
* **Action:**
  1. Run:
     ```bash
     python -m evals.run --compare
     ```
  2. Show the comparison table displaying **Task F1 (0.9024)** and **Valid JSON Rate (100%)**.
  3. Run:
     ```bash
     python -m pytest tests/ -v
     ```
  4. Show all 92 tests passing.
* **Voiceover:**
  > *"Every prompt iteration is rigorously benchmarked against a 28-sample ground-truth dataset in CI—measuring task precision, recall, and priority accuracy. Life Inbox combines instant capture with production AI engineering."*

---

## 📹 Post-Production & GIF Generation

To generate an optimized README preview GIF from the video recording:

```bash
# Convert MP4 to high-quality compressed GIF with palette generation
ffmpeg -y -ss 00:00:00 -t 00:01:20 -i demo.mp4 \
  -vf "fps=15,scale=1080:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  docs/demo.gif
```
