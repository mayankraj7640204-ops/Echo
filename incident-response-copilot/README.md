# Incident Response Memory Copilot

This MVP targets the hackathon's Engineering and DevOps incident response idea. It runs as a Band.ai agent, uses Hindsight for persistent incident memory, and focuses on one workflow: recall relevant postmortems, prepare a cautious mitigation brief, then save the verified resolution.

## What it demonstrates

- A first response can search past incidents by service, symptom, error, or recent change.
- Hindsight reflect turns the retrieved incident history and current facts into a brief that separates facts from hypotheses.
- After the operator confirms a resolution, the agent records the postmortem so the next similar incident starts with better context.
- Historical actions are treated as precedent, not as authorization to repeat a risky change.

The public interactive demo uses synthetic incidents in `hh3-incident-response`. The Login link opens a command dashboard backed by the separate `echo-live-incidents` Hindsight bank. It starts empty and learns only from outcomes an operator confirms and saves. In the live workspace, Echo compares the report with confirmed team cases, sends the incident details and up to three relevant case summaries to the real Rock and Salt agents in Band, and shows their live investigation and safety review. Rock identifies similarities without assuming the cause is the same; Salt checks proposed steps against the operator's constraints. Neither agent has production access or can run a change. Hindsight and Band credentials stay on the server.

## Setup

1. Copy .env.example to .env and add a Hindsight Cloud API key. The project uses https://api.hindsight.vectorize.io by default. `GITHUB_REPOSITORY` selects the repository used for numeric issue lookup. Public repositories need no GitHub token; for a private repository, set `GITHUB_TOKEN` to a fine-grained token with read-only Issues access.
2. The ignored agent_config.yaml is configured to use the existing Rock agent identity on Band.ai.
3. Install dependencies and create the two separate memory banks (the live team bank starts empty):

   python3 -m venv .venv
   .venv/bin/python -m pip install -e .
   .venv/bin/python setup_memory.py
   .venv/bin/python setup_live_memory.py

4. Start the website and Hindsight-backed demo API from this directory:

   .venv/bin/python web_api.py

   Open http://127.0.0.1:8000. “See the workflow” opens a prepared, plain-language walkthrough using fictional example prompts and answers. “Try a live demo” takes you to the editable incident form, which searches Hindsight and asks Rock and Salt for live reviews. The Hindsight and Band user keys stay in `.env` and are never sent to the browser. The demo bank contains fictional incidents, separate from the live team bank. The save-resolution form writes to memory only after the operator checks the confirmation box. When Band credentials and `rock-salt-agents/agent_config.yaml` are configured, the web server starts both Band workers automatically.

   The top “Login” link opens http://127.0.0.1:8000/dashboard.html. The dashboard reads live Hindsight memory counts and recent verified outcomes. Its incident workspace is http://127.0.0.1:8000/workspace.html. These pages are a prototype, not user authentication. They search only the separate `echo-live-incidents` bank. Add cases over time through the operator-confirmed save form; do not seed demo data into that bank. For live reviews, `BAND_USER_API_KEY`, `BAND_ROCK_AGENT_ID`, and `BAND_SALT_AGENT_ID` must be set in the server environment. The web server starts both Band workers automatically. `rock-salt-agents/rock_agent.py` and `salt_agent.py` use the Codex CLI in read-only mode. On macOS, set `CODEX_CLI_PATH` if it is not on PATH. If either agent is offline or fails, Echo shows an error instead of presenting a sample response as live.

   Sidebar features open dedicated pages: `/memory.html` searches confirmed team cases and lets an operator add one sanitized, approved past incident at a time, `/review.html` runs the live Band review, and `/outcomes.html` records a verified result and shows recent saved outcomes. Each page links to the next step in the incident workflow. The memory form requires explicit approval and rejects duplicate incident references. In the live incident workspace, a responder can start with an incident ID: Echo checks exact Hindsight history first, then tries a read-only GitHub Issue lookup when the ID is numeric. Set `GITHUB_REPOSITORY=owner/repository` to choose the incident repository. Public repositories need no token; for private repositories, `GITHUB_TOKEN` must have read-only Issues permission. Issue descriptions are sent to Hindsight and Rock/Salt for that review but never saved as team memory automatically. Confirm a resolution before saving it.

The Codex CLI must be installed and authenticated on this machine. Both workers use read-only mode and do not have production tools. Run `seed_demo_data.py` only for the separate fictional demo bank; never seed those examples into the live team bank.

## 60-second demo

1. Before seeding, ask: “Checkout API p95 is 4.8 seconds after today's deploy, with intermittent 502s and a saturated database pool. What should I check first?”
2. Show that the agent reports no relevant prior incident memory and separates current facts from unknowns.
3. In another terminal, run .venv/bin/python seed_demo_data.py. Ask the same question again. Show the agent retrieve INC-1042 and INC-0988 and identify the shared connection-pool pattern.
4. Confirm a simulated resolution and ask the agent to save a postmortem.
5. Ask a similar incident question again. Show that the agent recalls the newly recorded outcome and prevention step.

For a clean memory-before/memory-after comparison, create a fresh Hindsight bank and start with it empty.

## Hackathon deliverables to prepare

- Publish the code in a clean GitHub repository.
- Record a short demo video using the flow above.
- Prepare a live Band.ai demo and explain exactly where Hindsight retain, recall, and reflect appear.
- Complete the article, social post, and video requested by the hackathon content guide.

## Evaluation evidence

- **Innovation:** Echo compares symptoms, service, and impact across IDs and wording. The eraser-delivery example surfaces the saved pencil-delivery case while making clear that a similar report does not prove the cause is the same.
- **Hindsight memory:** the live bank begins empty, verified outcomes require operator confirmation, and future searches use those saved lessons. Fictional demo records stay in a separate bank.
- **Technical implementation:** live responses fail clearly when Band is unavailable instead of falling back to fabricated text; numeric case lookup is read-only GitHub Issues access; credentials remain server-side; duplicate saved IDs are rejected.
- **User experience:** responders can start fresh or investigate an existing case, provide only details they know, inspect similar cases and separate Rock/Salt reviews, then save a verified result.
- **Real-world impact:** teams can add approved post-incident lessons and use them during later response. Production monitoring integrations and real team authentication are future work.
