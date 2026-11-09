# Echo

Echo is an incident response copilot. It searches approved incident history, prepares a cautious response plan, and saves a resolution to Hindsight only after an operator confirms the outcome.

## Run locally

1. Create `incident-response-copilot/.env` from `.env.example` and add your Hindsight Cloud API key. The key stays on the server. The app can also read GitHub Issues by number from the configured repository; public repositories need no token. For a private repository, set an optional read-only `GITHUB_TOKEN` and `GITHUB_REPOSITORY=owner/repository`.
2. Install the app and prepare its separate demo and team memory banks:

   ```sh
   cd incident-response-copilot
   python3 -m venv .venv
   .venv/bin/python -m pip install -e .
   .venv/bin/python setup_memory.py
   .venv/bin/python setup_live_memory.py
   .venv/bin/python web_api.py
   ```

3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000). “See the workflow” opens a prepared walkthrough; “Try a live demo” analyzes an incident against fictional sample cases; “Login” opens the command dashboard, with live Hindsight memory status and a link to the separate incident response workspace.

The live workspace uses the separate `echo-live-incidents` Hindsight bank. Operators can add sanitized past cases after confirming they are approved to share; they can also add confirmed outcomes after new incidents. When a numeric incident ID is supplied and no exact saved case exists, Echo can look up a read-only GitHub Issue from `GITHUB_REPOSITORY`, then compare its details with Hindsight. Echo does not connect to or change production systems. The workspace is a prototype and does not provide user authentication.

## Project layout

- `outputs/halden-port-ops/` — Echo website, walkthrough, dashboard, incident workspace, memory search, review, and verified-outcome pages.
- `incident-response-copilot/` — FastAPI backend and Hindsight integration.
- `rock-salt-agents/` — Band.ai agent examples. Their local credentials and configuration files are excluded from Git.

Never commit `.env` files, agent API keys, or production incident data. Use sanitized incidents approved by your team.
