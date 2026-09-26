# Attribute Spend by Initiative, not by a fixed task-type taxonomy

The main unit of attribution is the Initiative: the business goal a Session served, inferred by an LLM from the Session's content and grouped across Sessions. We chose it over a fixed list of task types (feature, bugfix, refactor, …) because the question Admins actually ask is "what did we spend on storage work?", and nothing on the market answers it. Competitors attribute by API key, tag or directory group.

## Consequences

Initiatives differ from Customer to Customer, so a cross-Customer "cost per task type" benchmark isn't free anymore. If benchmarks are wanted later, a task-type label can be added as a second axis without changing Initiative.
