# Proof Library — Usman's REAL projects

The ONLY source of experience/proof claims allowed in replies and DMs.
Never invent beyond these. Pull the genuinely-closest entry; if none fits, claim no proof.
Keep references vague on client identity, specific on the technical result.

## LinkedIn "Digital FTE" — autonomous content + lead engine
- Fully autonomous content engine: topic selection → drafting → branded image gen → publishing
  → comment classification → lead scoring → weekly reporting, single approval step.
- Orchestrated on GitHub Actions at zero hosting cost. Multi-provider LLM layer (4 providers)
  with retry, exponential backoff, idempotent dedup so each stage self-recovers.
- RAG on Supabase pgvector to ground posts and prevent repetition.
- Playwright pipeline turning HTML templates into branded 1080x1350 PNG infographics.
- Twice-daily lead-hunting: pulls posts, LLM-scores lead quality, drafts replies/DMs,
  deduped against Supabase so a lead never resurfaces.
- Usable proof lines: "built an autonomous content+lead system that runs itself on a cron",
  "wired multi-LLM fallback so one provider going down doesn't kill the run",
  "dedup against a db so the same lead never comes back twice".

## WordPress multi-site publishing system
- Autonomous pipeline generating, scheduling, publishing 2 articles/day across 5 WordPress sites.
- Content staged in Airtable before publication; manual override to queue extra posts on demand.
- 30-minute scheduling gap auto-enforced between posts to respect platform rate limits.
- Usable proof lines: "ran a pipeline publishing to 5 sites a day with zero manual steps",
  "learned the hard way to build in rate-limit gaps so the platform doesn't throttle you".

## n8n / automation consulting (Upwork, Fiverr)
- Production automation systems for clients: RAG pipelines (OpenAI Agents SDK), n8n workflows,
  AI chatbots, LLM integrations via OAuth 2.0 into existing business systems.
- Usable proof lines: "did this exact kind of integration for a client through webhooks instead of
  the native connector", "built the same flow in n8n for someone last month".

## NCAI internship — automation engineering
- n8n automations wiring APIs, webhooks, scheduled triggers into hands-off pipelines.
- LangChain/LangGraph multi-step reasoning and stateful agent flows; retrieval + prompt design.

## Flutter / mobile apps
- Real-time Blood Donation app: multi-role, real-time matching by blood type + GPS proximity,
  Firestore real-time listeners, role-based auth, configurable-radius Google Maps search, FCM push.
- Costify — construction expense management: Clean Architecture, offline-first sync, real-time
  Firebase backend, role-based access (admins, contractors, clients).
- Exarth internship: cross-platform Flutter/Dart features, REST API integration, Firebase, team git.
- Usable proof lines: "built a couple of production Flutter apps with real-time firebase + offline sync",
  "shipped a multi-role app with gps matching and live updates".

## Stack (for "what would you use" credibility)
Python, LangChain/LangGraph, n8n, Playwright, Supabase, GitHub Actions, Next.js, Flutter,
Apify, Discord bots, Airtable, OpenAI/Anthropic/Gemini/Groq APIs, OAuth 2.0, webhooks.
