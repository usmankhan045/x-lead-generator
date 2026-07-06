# Lead Scoring Prompt

Qualify ONE tweet as a sales lead for Usman, a freelance AI/automation engineer who sells:
custom automation (Python, n8n), AI agents/chatbots (LangChain/LangGraph, RAG), mobile apps
(Flutter), websites (Next.js), integrations (APIs, webhooks, CRMs, Shopify, Airtable).

Score 0-100 with EXACTLY this rubric (sum the parts, then subtract red flags):

- PAIN 0-25: explicit, first-person, CURRENT problem with specifics = 20-25; vague pain = 10-19; hypothetical/none = 0-9.
- AUTHORITY 0-25: bio says founder/CEO/owner/realtor/coach/store-owner OR business link OR "my store/clients/team" = 20-25; likely business owner = 10-19; employee/student/unclear = 0-9.
- FIT 0-20: maps directly to Usman's services = 15-20; adjacent = 8-14; not his domain = 0-7.
- URGENCY 0-15: actively asking for help/recs, "asap", budget mentioned = 11-15; open question/strong frustration = 5-10; passive = 0-4.
- MARKET 0-15: location in target list {TARGET_MARKETS} = 15; unknown/ambiguous = 5; confirmed outside = 0 (also set market.in_target=false).

RED FLAGS (subtract 10-40 each, list them): author is themselves selling/promoting a service or product (competitor, "I built/I help/stop wasting...DM"); job seeker/recruiter/intern posting; engagement bait/giveaway/thread advice; crypto/web3/forex/betting.

CONFIDENCE 0-100 (separate — how complete the signals are, NOT the score): +20 informative bio, +20 location identified, +25 pain stated explicitly (vs inferred), +15 full metadata, +20 fluent natural English. A strong lead with no bio/location = high score but low-medium confidence.

TWEET_TYPE (exactly one): vent | question-ask | hire-ask | cost-ask | tool-rec-ask | automation-doubt

MARKET: infer country from the location field first (parse "Austin TX"->US, "Manchester"->GB). Weak hints (timezone, phrasing) support but never override an explicit location. Never guess country from name alone; if unreliable, country=null.

Output STRICT JSON only:
{"score":<0-100>,"subscores":{"pain":<n>,"authority":<n>,"fit":<n>,"urgency":<n>,"market":<n>},"red_flags":[{"flag":"<name>","penalty":<n>}],"confidence":<0-100>,"confidence_reasons":["<short>"],"tweet_type":"<one>","niche":"<automation|app-web|ecommerce|coaching|real-estate|other>","market":{"country":"<ISO2 or null>","in_target":<true|false|null>,"basis":"<what you used>"},"reasoning":"<one sentence>"}

TWEET
@{handle} ({author_name}) | bio: {bio} | location: {location}
followers {followers} / following {following} | account {account_age_days}d old | {posts_per_day} posts/day | tweet {tweet_age_hours}h old
text: {text}
