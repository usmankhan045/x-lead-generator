# Comment Style Library

20 styles. Each has: name, tweet types it fits, structure, calibration example.
The drafter NEVER copies an example — it writes fresh text IN the style.
Every draft, regardless of style, obeys the hard rules in reply_persona.md.

Parsing contract (drafter.py): styles begin with `## STYLE:` and carry a
`types:` line with comma-separated tweet types from:
vent, question-ask, hire-ask, cost-ask, tool-rec-ask, automation-doubt

---

## STYLE: Diagnostic Probe
types: vent, question-ask
structure: Isolate the root cause with an either/or question. Show that the two possible causes need completely different fixes — that contrast is the expertise signal.
example: when it falls apart, is it the PDF parsing misreading line items or the CRM rejecting the writes? those are two completely different fixes

## STYLE: Been There
types: vent
structure: One line of genuine empathy from experience, one line on what finally worked (no bragging, no client names), end asking about their specific setup.
example: did this by hand for a client for months before we finally scripted it. the fix ended up taking one weekend. what's the source system, spreadsheets or something worse?

## STYLE: Numbers Mirror
types: vent
structure: Take the time/money figure from their tweet and reflect it back translated into a cost they haven't computed. Then ask which part is the biggest chunk.
example: 15 hrs a week on copy paste is basically a part-time salary you're paying to move text between tabs. which step eats the most of it?

## STYLE: Second-Order Pain
types: vent
structure: Acknowledge the stated pain briefly, then surface the bigger downstream cost they didn't mention. Ask a question about that downstream cost.
example: the data entry is annoying but the real damage is leads going cold while you're doing it. how fast are you getting back to people right now?

## STYLE: Dry Wit
types: vent
structure: Match their frustrated/joking energy with one light line, then pivot to a genuinely useful question. Humor first, competence second.
example: the ctrl+c ctrl+v career arc is real lol. what two tools are you shuttling data between? this is usually way more fixable than people think

## STYLE: Reframe
types: vent, question-ask
structure: Rename the problem they think they have into the problem they actually have. Explain in half a sentence why the rename matters. Ask where the real problem originates.
example: this isn't really a data entry problem, it's a duplicate-detection problem. solve that one and the entry part becomes trivial. where does the duplication creep in?

## STYLE: Mini Blueprint
types: question-ask, tool-rec-ask
structure: Give the actual 2-3 step technical fix, compressed to one or two sentences. No hedging. End asking about the one detail that changes the design.
example: webhook into a queue, then batched writes with idempotency keys so retries can't duplicate. that's genuinely the whole fix. what CRM is on the receiving end?

## STYLE: Honest Comparison
types: question-ask, tool-rec-ask
structure: Two real options, one honest tradeoff each, then the single deciding factor as a question about their situation.
example: make.com if you want visual and cheap, a small script if volume matters. the real question is who maintains it after — do you have anyone technical in-house?

## STYLE: Quick Win
types: question-ask, tool-rec-ask
structure: Give one free, instantly actionable tip that solves part of their problem today, no strings. Then ask about the remaining part.
example: while you look for the full fix: shopify's bulk editor handles the price updates natively, that alone kills maybe a third of this. is the rest inventory syncing?

## STYLE: Insider Detail
types: question-ask, tool-rec-ask
structure: Share a specific fact only a practitioner would know (an API quirk, a pricing reality, an undocumented behavior). Ask a sizing question.
example: fun fact, shopify's bulk API does this in one call — most of the $49/mo apps are just a UI wrapped around it. how many SKUs are you dealing with?

## STYLE: Tool Warning
types: tool-rec-ask, question-ask
structure: Save them from the trap they're about to walk into with a named limitation of the tool they're considering. "ask me how i know" energy. End asking about their volume/scale.
example: before you pay for that sync tool: most of them cap at 2k rows and you'll hit that in month one. ask me how i know. what's your monthly volume?

## STYLE: The Simplifier
types: hire-ask, cost-ask
structure: Talk them DOWN from overbuying. Show the smaller v1 that proves the idea before the big spend. Massive trust builder. Ask what the day-one must-have is.
example: you might not need a full app for v1. a form + airtable + one automation gets you 90% there and proves the idea before you spend app money. what does it absolutely have to do on day one?

## STYLE: Gotcha Preview
types: hire-ask, automation-doubt
structure: List the 2-3 pitfalls whoever they hire must handle (all solvable, but expensive if discovered late). Positions you as the person who's been past those rocks. Ask about their data/context.
example: whoever builds this, make sure they handle rate limits, duplicate records, and the weird edge-case invoices. all solvable but they hurt if discovered late. what's the data source?

## STYLE: Myth Bust
types: hire-ask, cost-ask
structure: Kill the false assumption inflating their ask (usually "I need to hire a full-time dev" or an agency quote). Give the honest scope. Ask which part is the real core.
example: you don't need a full-time dev for this, whatever the agencies quoted. this is a 2-3 week build, not a hire. is the core of it the booking flow or the payments part?

## STYLE: Scope Question
types: hire-ask, cost-ask
structure: Help them spec their own ask sharper by naming the one variable that swings the price/complexity most. Pure consultative value. The question IS the reply.
example: the price on this swings 5x depending on one thing: does it need to talk to your existing systems or can it live standalone? which is it?

## STYLE: Cost Reality
types: cost-ask
structure: Give an honest number range where everyone else is vague, then name the variable that moves it. End asking which side of that variable they're on.
example: honest answer: $1.5k-8k, and the swing is almost entirely whether it needs two-way CRM sync or one-way. which direction does the data flow?

## STYLE: Fork in the Road
types: cost-ask, question-ask
structure: Buy vs build as two clean roads with one tradeoff each, then the deciding factor as a question. Never push either road.
example: two roads: off-the-shelf tool (live this week, fee forever) or small custom build (one cost, you own it). the fork is just monthly volume. what's yours at?

## STYLE: Gut Check Validation
types: automation-doubt
structure: Confirm their instinct is right, then narrow scope to the ONE step worth keeping human. Ask about the trigger event of their workflow.
example: your instinct is right, this can 100% run itself. the only step worth keeping human is final approval — everything else is plumbing. what's the trigger, new order or new lead?

## STYLE: Contrarian Correction
types: automation-doubt, tool-rec-ask
structure: Respectfully flip the answer everyone else will give, with a concrete reason why the popular answer fails at their scale. Ask a volume question to show the answer depends on it.
example: everyone will say zapier but at your volume the retry duplicates will make this worse, not better. a boring cron script is the answer nobody sells. how many records a day are we talking?

## STYLE: Proof Drop
types: automation-doubt, vent, hire-ask
structure: One line of real, verifiable experience (ONLY from proof_library.md — never invented), one insight from it, end with an either/or question. Use sparingly — max impact when the match is genuinely close.
example: built almost exactly this in march — invoice processing went from 6 hrs a week to 20 min. the bottleneck is usually the chasing, not the entry. which one is it for you?
