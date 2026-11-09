# Echo

Echo is an incident response copilot. It searches approved incident history, prepares a cautious response plan, and saves a resolution to Hindsight only after an operator confirms the outcome.

## Run locally

1. Create `incident-response-copilot/.env` from `.env.example` and add your Hindsight Cloud API key. The key stays on the server.
2. Install and start the web app:

   ```sh
   cd incident-response-copilot
   python3 -m venv .venv
   .venv/bin/python -m pip install -e .
   .venv/bin/python web_api.py
   ```

3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000). “See the workflow” opens a prepared walkthrough; “Try a live demo” analyzes an incident against fictional sample cases; “Login” opens the command dashboard, with live Hindsight memory status and a link to the separate incident response workspace.

The live workspace uses the separate `echo-live-incidents` Hindsight bank. It starts empty and learns only from operator-confirmed incidents. Echo does not connect to or change production systems. The workspace is a prototype and does not provide user authentication.

## Project layout

- `outputs/halden-port-ops/` — Echo website, walkthrough, and incident workspace.
- `incident-response-copilot/` — FastAPI backend and Hindsight integration.
- `rock-salt-agents/` — Band.ai agent examples. Their local credentials and configuration files are excluded from Git.

Never commit `.env` files, agent API keys, or production incident data. Use sanitized incidents approved by your team.
