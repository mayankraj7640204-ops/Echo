# Incident Response Memory Copilot

This MVP targets the hackathon's Engineering and DevOps incident response idea. It runs as a Band.ai agent, uses Hindsight for persistent incident memory, and focuses on one workflow: recall relevant postmortems, prepare a cautious mitigation brief, then save the verified resolution.

## What it demonstrates

- A first response can search past incidents by service, symptom, error, or recent change.
- Hindsight reflect turns the retrieved incident history and current facts into a brief that separates facts from hypotheses.
- After the operator confirms a resolution, the agent records the postmortem so the next similar incident starts with better context.
- Historical actions are treated as precedent, not as authorization to repeat a risky change.

The public interactive demo uses synthetic incidents in `hh3-incident-response`. The Login link opens a command dashboard backed by the separate `echo-live-incidents` Hindsight bank. It starts with no cases and learns only from outcomes explicitly confirmed and saved by an operator. From the dashboard, a responder can open the live incident workspace. Rock investigates; Salt independently reviews safety. These are two Hindsight-backed response roles in this web app; the separate Band.ai Rock and Salt examples remain Tom-and-Jerry roleplay agents and are not called by the web app. Echo does not connect to production systems or execute changes.

## Setup

1. Copy .env.example to .env and add a Hindsight Cloud API key. The project uses https://api.hindsight.vectorize.io by default.
2. The ignored agent_config.yaml is configured to use the existing Rock agent identity on Band.ai.
3. Install dependencies and create the two separate memory banks (the live team bank starts empty):

   python3 -m venv .venv
   .venv/bin/python -m pip install -e .
   .venv/bin/python setup_memory.py
   .venv/bin/python setup_live_memory.py

4. Start the website and Hindsight-backed demo API from this directory:

   .venv/bin/python web_api.py

   Open http://127.0.0.1:8000. “See the workflow” opens a prepared, plain-language walkthrough using fictional example prompts and answers. “Try a live demo” takes you to the editable incident form, which sends the incident to Hindsight from the server. The API key stays in .env and is never sent to the browser. The demo bank contains four synthetic incidents, not company data. The save-resolution form writes to memory only after the operator checks the confirmation box.

   The top “Login” link opens http://127.0.0.1:8000/dashboard.html. The dashboard reads live Hindsight memory counts and recent verified outcomes. Its incident workspace is http://127.0.0.1:8000/workspace.html. These pages are a prototype, not user authentication. They search only the separate `echo-live-incidents` bank. Add cases over time through the operator-confirmed save form; do not seed demo data into that bank. The page’s Rock and Salt names refer to two separate Hindsight-backed review roles, not the Band.ai roleplay agents.

   Sidebar features open dedicated pages: `/memory.html` searches confirmed team cases and lets an operator add one sanitized, approved past incident at a time, `/review.html` runs the Rock and Salt review live, and `/outcomes.html` records a verified result and shows recent saved outcomes. Each page links to the next step in the incident workflow. The memory form requires an explicit approval checkbox and rejects duplicate incident references. In the live incident workspace, a responder can start with only an incident ID. Echo checks that exact reference against saved team history; if no match exists, it explains that the ID alone cannot reveal the current service or impact and asks for one detail. Ticketing and monitoring integrations are not connected yet.

5. To use the Band.ai agent as well, start it in a second terminal:

   .venv/bin/python incident_agent.py

The Codex CLI must be authenticated on this machine. In Band.ai, open a chat with Rock and ask about a current incident.

The Band agent uses the existing Rock identity and runs with a read-only Codex sandbox. Its Hindsight tool can store memories, but it cannot change production systems. Run seed_demo_data.py once per fresh memory bank; it adds synthetic records to Hindsight.

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
