# LiquidPilot AI

Local d1 browser agent for Windows. Open **http://127.0.0.1:7870** after double-clicking **python main.py** in the parent folder. **the task controls and close the local Python process** stops this app and its owned processes. Existing Chrome windows are not owned or closed by LiquidPilot.

## Connect your Chrome and existing logins

1. In LiquidPilot, click **Connect Chrome**.
2. Open `chrome://extensions` in your normal Chrome profile, enable Developer mode, choose **Load unpacked**, and select `liquidpilot/extension`.
3. Open the website tab you want the agent to use. Click the LiquidPilot extension, paste the pairing code shown by the app, and click **Connect this tab**.
4. Return to LiquidPilot, leave **My Chrome tab** selected, enter an instruction, and start a task. The selected tab remains open for later tasks. Choose another tab using the extension when needed.

Chrome displays a debugger attachment banner. Disconnect using the extension at any time. Pairing codes expire after ten minutes and work once. The extension remembers the reconnect token for the Chrome session; restarting LiquidPilot requires a new pairing code. It never exports cookies or reads the password store. Website actions use the tab's existing session.

## Use it

- **YouTube:** connect a YouTube tab and ask “Find the latest Wartune video.” The agent searches the topic, opens the observed upload-date filter, compares dated matching video cards, and opens the newest match it inspected. It returns a video card with title, channel, publication evidence, and scope. “Play” or “run” explicitly requests playback. Search query under Task scope can override topic extraction. This supports English search labels and readable English relative publication ages; unsupported layouts stop instead of guessing. After an update, reload the extension at `chrome://extensions`, refresh LiquidPilot, and pair again.

- **Navigate:** connect a documentation website; ask “Find the authentication documentation.” Navigation follows observed links and records the matching page.
- **Extract:** choose Table extraction under Task scope; ask “Find the product specifications table and export its rows.” Download CSV, JSON, HTML, Markdown, and evidence ZIP from the result.
- **Forms:** choose Assisted mode and Form preparation. Supply visible field labels and values as JSON, for example `{"Name":"Demo User","Role":"Editor"}`. Supply the exact expected confirmation text. In connected Chrome each field edit and button action asks for approval because websites can autosave. The isolated test browser can prepare fields with its network frozen before final approval.
- **Images/documents:** use the paperclip or drop up to six files into the instruction box. Images are passed to d1; PDF, DOCX, and text files are locally extracted into bounded reference context. Attaching a file does not upload it to a website. Connected Chrome website file-upload and download automation are not implemented; use a manual browser upload. The isolated adapter supports approved file-upload/download tools.
- **Follow-up:** start a new task against the same connected Chrome tab; its page and login remain in place. Task histories are separate, so repeat any essential goal/field values.
- **Stop/pause:** use the task controls. An external action already in flight may have reached the website. Uncertain submissions are never retried.

## What is implemented, and limits

d1 is a **decision model**, not a free-form chat model. It chooses among observed, bounded browser actions through `/v1/systemone`; probabilities and actual tool outcomes are inspectable. This release supports structured navigation, table extraction, and explicit-field forms. It is not an unrestricted “do anything” agent. The optional local generative planner is not installed/configured; complex requests may require explicit URLs, field values, and success criteria. Missing capabilities and incomplete outcomes are reported.

Connected Chrome controls **one explicitly selected tab at a time**. The connector inspects the main document; cross-origin iframes, shadow-DOM applications, canvas controls, trusted-event-only controls, file inputs, and arbitrary keyboard shortcuts may require manual interaction. It does not bypass CAPTCHA or authentication. Chrome internal pages cannot be controlled. Existing website background requests continue normally; this adapter is not a network sandbox. See SECURITY.md.

The separate test browser uses Playwright with an isolated temporary profile, DNS-pinned egress proxy, blocked unsolicited writes, and controlled file transfers. It does not share existing logins. Search is an optional workflow; public search engines may challenge or block automation. A three-source public research benchmark remained partial; the app does not claim it passed.

## Hardware and local runtime

Configure compatible model weights and llama.cpp paths in config/settings.json. Weights and runtimes are not bundled.

Backend: Python 3.12, FastAPI, SQLite/WAL, DPAPI-protected Fernet vault. Frontend: React, TypeScript, Vite, Tailwind. A portable Python runtime and virtual environment are already installed in this folder. Default app settings live in `config/settings.example.json`; saved overrides use `config/settings.json`. Local planner adapters accept localhost HTTP only. No cloud AI service is configured.

## Development and verification

```powershell
.\.venv\Scripts\python.exe main.py
npm run build --prefix frontend
.\.venv\Scripts\python.exe -m pytest backend/tests -q --basetemp workspace/test-runs/my-new-run
.\.venv\Scripts\python.exe scripts/verify_ui.py
```

Use a new test output directory for each run. Tests use controlled local web servers with explicit test-only network grants. The extension integration test loads into a temporary test profile using the previously installed Playwright Chromium 1223; it does not test against private user accounts. See `RELEASE_REVIEW.md` for observed results.

Project layout: `backend/agent.py` action loop; `models.py` native d1/local planner; `browser.py` isolated Playwright adapter; `connected_browser.py` existing-Chrome adapter; `chrome_bridge.py` authenticated transport; `extension/` Chrome connector; `frontend/` UI; `workspace/` encrypted tasks, logs, and verification artifacts.
