# Lead Scoring Prompt

Qualify ONE tweet as a sales lead for Usman, a freelance AI/automation engineer who sells:
custom automation (Python, n8n), AI agents/chatbots (LangChain/LangGraph, RAG), mobile apps
(Flutter), websites (Next.js), integrations (APIs, webhooks, CRMs, Shopify, Airtable).

Score 0-100 with EXACTLY this rubric (sum the parts, then subtract red flags):

A REAL, SOLVABLE PROBLEM from someone who wants it fixed matters more than a fancy title.
Do NOT require a "founder/CEO" bio to score well.

- PAIN 0-30: explicit, first-person, CURRENT problem with specifics ("I spend 10 hrs/wk on X") = 24-30; clear but less specific = 14-23; vague/passing mention = 5-13; hypothetical/none = 0-4.
- AUTHORITY 0-18: runs a business/store/practice/side-project OR speaks as an operator ("my store/clients/team/customers") OR bio shows founder/owner/coach/realtor = 13-18; individual with a genuine need but no clear business signal = 6-12; clearly not a decision-maker (employee venting, student) = 0-5.
- FIT 0-22: maps directly to Usman's services (automation, AI agent/chatbot, app, website, integration) = 16-22; adjacent/solvable with a stretch = 8-15; not his domain = 0-7.
- URGENCY 0-15: actively asking for help/recs, "asap", budget/hiring mentioned, clear "I need this" = 10-15; open question or real frustration seeking a fix = 5-9; passive/rhetorical = 0-4.
- MARKET 0-15: location in target list {TARGET_MARKETS} = 15; unknown/ambiguous = 8; confirmed outside = 0 (also set market.in_target=false).

RED FLAGS (subtract 10-40 each, list them) -- THESE PROTECT QUALITY, keep applying hard: author is themselves selling/promoting a service or product (competitor / agency / "I built/I help/we help/stop wasting...DM/book a call"); job seeker/recruiter/"HIRING" vacancy posting; engagement bait/giveaway/thread advice; crypto/web3/forex/betting; pure content/thought-leadership with no personal need.

CONFIDENCE 0-100 (separate — how complete the signals are, NOT the score): +20 informative bio, +20 location identified, +25 pain stated explicitly (vs inferred), +15 full metadata, +20 fluent natural English. A strong lead with no bio/location = high score but low-medium confidence.

TWEET_TYPE (exactly one): vent | question-ask | hire-ask | cost-ask | tool-rec-ask | automation-doubt

MARKET: infer country from the location field first (parse "Austin TX"->US, "Manchester"->GB). Weak hints (timezone, phrasing) support but never override an explicit location. Never guess country from name alone; if unreliable, country=null.

NON-TWITTER SOURCES (e.g. a Hacker News "SEEKING FREELANCER" job post — empty bio/followers): these are companies ACTIVELY PAYING to hire, so they are high-intent buyers by definition. Judge from the POST TEXT itself and score generously when the work fits:
  - AUTHORITY 13-18: a company posting a paid project is a decision-maker with budget (no bio needed).
  - PAIN = how concrete/relevant the project is: a clearly-defined project they will pay for = 18-26 (their "pain" is implicit — they've decided to spend money).
  - URGENCY 10-15: they are hiring RIGHT NOW; that IS urgency. Do not require emotional complaint language.
  - MARKET: parse country from the post ("SWITZERLAND", "Remote", "Location: Berlin", "SF-based").
  - Do NOT apply the "recruiter/HIRING vacancy" red flag here — hiring a freelancer/contractor is exactly the buyer we want. Only red-flag if the role is clearly unrelated to Usman's services (e.g. hiring a sales rep or a designer only).

Output STRICT JSON only:
{"score":<0-100>,"subscores":{"pain":<n>,"authority":<n>,"fit":<n>,"urgency":<n>,"market":<n>},"red_flags":[{"flag":"<name>","penalty":<n>}],"confidence":<0-100>,"confidence_reasons":["<short>"],"tweet_type":"<one>","niche":"<automation|app-web|ecommerce|coaching|real-estate|other>","market":{"country":"<ISO2 or null>","in_target":<true|false|null>,"basis":"<what you used>"},"reasoning":"<one sentence>"}

TWEET
@{handle} ({author_name}) | bio: {bio} | location: {location}
followers {followers} / following {following} | account {account_age_days}d old | {posts_per_day} posts/day | tweet {tweet_age_hours}h old
text: {text}
