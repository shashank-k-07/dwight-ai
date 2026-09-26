# Dwight

Dwight shows an enterprise what its AI agents are spending money on and why, then recommends how to spend less. It attributes metered agent spend to the work it served and flags the spend that was waste.

## Language

### Who's involved

**Customer**:
The enterprise that runs Dwight over its own agent usage.
_Avoid_: Tenant, org, account

**Admin**:
A person at the Customer who uses Dwight to manage agent spend, typically the CTO or an IT admin.
_Avoid_: User, operator

**Member**:
An employee of the Customer whose Agent Sessions Dwight observes.
_Avoid_: User, developer, employee

**Business Function**:
A top-level division of the Customer, such as Engineering, Marketing or Operations.
_Avoid_: Department, vertical, org

**Team**:
A group of Members within a Business Function, such as Platform or Payments.
_Avoid_: Squad, group

### What's observed

**Agent**:
An AI tool that runs multi-step work on a Member's behalf and bills by usage.
_Avoid_: Bot, assistant, copilot

**Session**:
One continuous run of an Agent by one Member toward one goal. Sessions are what Dwight attributes and scores.
_Avoid_: Conversation, chat, trace, job

**Spend**:
The metered dollar cost of the tokens used by a Session, or by a group of Sessions.
_Avoid_: Cost, bill, usage

**Initiative**:
The business goal a Session served, such as "storage cost reduction" or "auth migration". Dwight infers it from the Session's content and groups related Sessions under it.
_Avoid_: Task type, project, category, use case

### What's found

**Waste**:
Spend that bought nothing: the same work would have produced the same result without it.
_Avoid_: Inefficiency, overspend

**Waste Pattern**:
A named, recognisable way a Session produces Waste. The known ones are Redundant Read, Cache Miss, Runaway Loop and Model Overkill.
_Avoid_: Anti-pattern, issue

**Redundant Read**:
A Waste Pattern where an Agent re-sends content it has already sent in the same Session.

**Cache Miss**:
A Waste Pattern where the Agent pays full price for context that could have been served from the prompt cache.

**Runaway Loop**:
A Waste Pattern where an Agent repeats the same actions without making progress.

**Model Overkill**:
A Waste Pattern where a Session used a more expensive model than its work needed.

**Measured Waste**:
Waste computed directly from a Session's token counts, with no judgement involved. Redundant Read, Cache Miss and Runaway Loop produce Measured Waste.
_Avoid_: Savings, confirmed waste

**Estimated Saving**:
Spend Dwight believes could have been avoided, based on a model's judgement rather than arithmetic. Model Overkill produces Estimated Savings.
_Avoid_: Projected waste, potential savings

### Across Sessions

**Trail**:
The ordered list of resources (docs, files, URLs) that a Session's Agent read, with the token count of each.
_Avoid_: Path, history, log

**Discovery**:
A fact an Agent worked out during a Session that it did not have at the start, recorded as one short statement.
_Avoid_: Learning, insight, finding

**Recurring Discovery**:
Work that many Sessions in one Initiative each redo because none of them can see what earlier Sessions found. It shows up in two ways: a common path (the same resources read in most Trails) or a repeated Discovery (the same Discovery reached separately in many Sessions). It isn't Waste within any one Session. Only a change at the Customer, such as a new doc or shared memory, removes it.
_Avoid_: Duplication, redundant work

### What's recommended

**Recommendation**:
A proposed change aimed at one target (an Initiative, a Team or a Policy). It applies a Practice to the Customer's Infra Profile and carries its Measured Waste or Estimated Saving in dollars.
_Avoid_: Suggestion, insight, tip, playbook

**Draft**:
A ready-to-review artifact that Dwight writes and attaches to a Recommendation: a doc consolidated for an Initiative, or a set of memory entries for it. The Customer puts it in place; Dwight doesn't host it.
_Avoid_: Generated doc, output, template

**Practice**:
A curated, versioned way of working that removes one or more Waste Patterns, such as "cache-friendly prompt layout" for Cache Miss. Every Recommendation cites the Practice it applies.
_Avoid_: Best practice, tip, guideline

**Practice Library**:
Dwight's curated set of Practices.
_Avoid_: Knowledge base, playbook library

**Infra Profile**:
What Dwight knows about the Customer's AI setup: available models and tiers, gateway, caching, internal tools and docs sources, and main repositories. Part of it is inferred from Sessions and part is declared by an Admin.
_Avoid_: Environment, stack, config

**Policy**:
A rule an Admin applies to a Team or Business Function that limits which models its Members' Agents may use. The Customer's own gateway enforces it, not Dwight.
_Avoid_: Guardrail, restriction, lockdown
