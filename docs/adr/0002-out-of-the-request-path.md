# Dwight observes and advises; it never sits in the request path

Dwight reads telemetry after the fact and produces Recommendations. It does not proxy model traffic. Most tools in this space (LiteLLM, Portkey, Helicone, OpenRouter) are gateways, so readers will expect Dwight to be one too. We chose not to be, because sitting in the path of every agent call means taking on latency, uptime and data-custody obligations, the heaviest trust ask an enterprise can face. When an Admin applies a Policy, Dwight writes it as configuration for the gateway the Customer already runs (e.g. an Azure API Management policy or a LiteLLM team model allowlist), and that gateway enforces it.

## Consequences

Dwight cannot block spend as it happens; it can only prevent a repeat once a Policy is applied. Budget hard-stops stay with the Customer's gateway.
