# Storage cost reduction: initiative doc

Written by Dwight for Agents working on Storage cost reduction. 10 of 10 Sessions read the same 4 docs to get started (about 23,892 tokens each time). This doc keeps only what those Sessions needed, with exact values copied from the sources. For anything not covered here, open the linked source.

Sources: [Runbook: Lifecycle Migrations with blobctl](company-docs/blobctl-migration-runbook.md), [Storage Cost Dashboard & Bucket Inventory](company-docs/storage-cost-dashboard.md), [Storage Architecture & Service Ownership](company-docs/storage-service-ownership.md), [Storage Tiering & Retention Policy](company-docs/storage-tiering-policy.md)

## Runbook: Lifecycle Migrations with blobctl

Source: [company-docs/blobctl-migration-runbook.md](company-docs/blobctl-migration-runbook.md)

### Scope: which buckets are in play (§3)
- In scope: **"Policy compliant" = "No"** on the Storage Cost Dashboard & Bucket Inventory.
- **"Yes"**: already compliant; leave alone unless the owning team requests a change.
- **"Exempt"**: never touched, even if expensive.

### Pre-flight checklist (§4)
- Bucket in scope per §3.
- Data class and current lifecycle rule from the cost dashboard.
- Owning team, its handle, and its storage approver from Storage Architecture & Service Ownership.
- Services that read the bucket and their service tiers.
- Average object size from the dashboard.
- Target schedule from Storage Tiering & Retention Policy, after applying every override.
- Change ticket `CHG-` in the `STORCHG` queue with bucket, target schedule, planned exception code.
- Write the target schedule into the change ticket before touching blobctl.

### Transitions and expiry (§5.1)
- `--transition <days>:<STORAGE_CLASS>`; `<days>` = days since object creation; list ascending.
- `<STORAGE_CLASS>` is the S3 storage class name (e.g. `STANDARD_IA`), not the Kestrel tier name; `Warm`/`Cold` are rejected.
- Objects start in `STANDARD`; never add a transition to `STANDARD`.
- Include only tiers the bucket uses after overrides.
- `--expire <days>` = days since object creation; omit only if the data class has no expiry. If unsure, the answer is in the data class schedule on the policy page, not the current rule.

### Rule id convention (§5.2)
- `<owning-team-handle>-<bucket name without the "kst-" prefix>-v<N>`
- `<owning-team-handle>` = owning team's handle, not the reader/writer team's.
- `N` = version in the bucket's current lifecycle rule + 1, or 1 if no rule.
- New rule replaces the old one; no separate delete.
- An expiry-only current rule still counts; bump its version.

### Exception codes (§5.3)
| Code | Meaning |
|---|---|
| `NONE` | Tiered all the way to Frozen. |
| `STATUTORY_RETENTION` | Statutory retention prevents Frozen. |
| `TIER1_READER` | A Tier-1 service reads the bucket; Frozen not permitted. |
| `DATA_CLASS_CAP` | Data class schedule caps below Frozen. |
| `SMALL_OBJECTS` | Average object size too small for archive tiers. |

Precedence if more than one applies: 1 `STATUTORY_RETENTION`, 2 `TIER1_READER`, 3 `DATA_CLASS_CAP`, 4 `SMALL_OBJECTS`. Record one code, not a list; a comma-separated value breaks the FinOps quarterly rollup.

### Running the migration (§6)
**Plan** (dry run; validates and records a plan against the rule id):
```
blobctl plan --bucket s3://kst-telemetry-raw-eu --rule-id data-infra-telemetry-raw-eu-v1 --transition 30:STANDARD_IA --transition 90:GLACIER_IR --transition 365:DEEP_ARCHIVE --expire 1095
```
Always pass `--bucket` as the full `s3://` URI. Re-planning the same rule id overwrites the earlier plan.
Note: Sessions found blobctl 2.x requires a bare bucket name; the `s3://` URI form is rejected with `E_BADREF`.

**Apply** (only after a plan exists for the same rule id):
```
blobctl apply --rule-id <rule-id> --change <CHG-number> --approver <@handle of the owning team's storage approver>
```
`--approver` is the owning team's storage approver, not your manager or the Tidewater lead. `apply` fails if no plan exists for the rule id.

**Status**:
```
blobctl status
```
Confirm the rule appears applied with the right change number and approver. In an interactive terminal, pipe through `cat` or run non-interactively; the pager can swallow the last line.

**Update the change ticket** with: final rule id, exception code (§5.3), a paste of the relevant `blobctl status` lines, and the promotion Wednesday you expect.

### Promotion and freezes (§2, §8)
- All lifecycle changes land in the staging control plane first; agents never touch production directly.
- Weekly promotion job: Wednesdays 14:00 ET, run by Storage on-call.
- Applied and approved by Wednesday 12:00 ET is normally picked up that week.

| Freeze | When | Scope |
|---|---|---|
| Month-end close | Last 3 business days of the month through the 2nd business day of the next month | Buckets owned by or read by **Billing**; applies to staging applies as well as promotion |
| Peak season | Monday before US Thanksgiving through January 5 | All production storage changes, except break-glass |
| Company holidays | Kestrel observed holidays | No promotion job; next Wednesday picks up |

### Tool, owner and version (§1, §13, §14)
- Tool: blobctl, repo `kestrel/blobctl`, installed at `bin/blobctl`.
- Runbook applies to blobctl 1.9; 2.x is rolling out (see `#blobctl-dev`).
- Owner: Data Infrastructure / Storage on-call (`data-infra-primary`), PagerDuty rotation; owns the weekly promotion job.

## Storage Cost Dashboard & Bucket Inventory

Source: [company-docs/storage-cost-dashboard.md](company-docs/storage-cost-dashboard.md)

### Price sheet (§5)
USD per GB-month; **1 TB = 1,000 GB**. eu-central-1 normalised to us-east-1 list prices, so EU buckets are priced with the same numbers as US buckets.

| Storage class | USD per GB-month |
|---|---|
| STANDARD | 0.023 |
| STANDARD_IA | 0.0125 |
| GLACIER_IR | 0.004 |
| DEEP_ARCHIVE | 0.00099 |

Storage only; request, transition and retrieval fees excluded (FinOps: <2% of S3 cost).

### Steady-state savings method (§6)
- monthly cost after = sum over age bands of (band TB × 1000 × price of the class the policy puts that band in).
- Bands older than the expiry age are deleted → cost 0.
- Saving = current monthly cost − cost after. Keep full precision through the calculation; round only the final figures to cents.
- Ignore request, transition and retrieval fees.
- Steady state = once the rule has run long enough that every object sits in its target class; not the first month after a change.
- The class "the policy puts that band in" is defined by the Storage Tiering & Retention Policy, including its overrides. Deepest permitted storage class and exception codes per bucket come from that policy.

### Non-compliant bucket inventory (§7)
Snapshot taken 2026-09-01. Age bands in TB; age is days since object creation. Monthly cost is list-price-equivalent at §5.

| Bucket | Region | Data class | Current class | Size TB | 0-30d | 30-90d | 90-365d | >365d | Lifecycle rule | Monthly cost USD |
|---|---|---|---|---|---|---|---|---|---|---|
| s3://kst-telemetry-raw-prod | us-east-1 | telemetry-raw | STANDARD | 820 | 60 | 110 | 380 | 270 | none | 18,860.00 |
| s3://kst-telemetry-raw-eu | eu-central-1 | telemetry-raw | STANDARD | 210 | 15 | 30 | 95 | 70 | none | 4,830.00 |
| s3://kst-pod-images-prod | us-east-1 | pod-images | STANDARD | 540 | 25 | 40 | 175 | 300 | mobile-apps-pod-images-prod-v1 (expiry only) | 12,420.00 |
| s3://kst-app-logs-prod | us-east-1 | app-logs | STANDARD | 310 | 95 | 170 | 45 | 0 | none | 7,130.00 |
| s3://kst-ml-snapshots | us-east-1 | ml-training-snapshots | STANDARD | 260 | 20 | 35 | 105 | 100 | none | 5,980.00 |
| s3://kst-support-attachments | us-east-1 | support-attachments | STANDARD | 36 | 4 | 6 | 12 | 14 | none | 828.00 |

Total S3: **55,351.50 / month** (August 2026 snapshot, taken 2026-09-01).

Note: Sessions found the prod environment is not available to this credential; only staging is permitted.

Notes:
- s3://kst-pod-images-prod rule `mobile-apps-pod-images-prod-v1` is **expiry-only**: deletes objects at end of retention, no storage class transitions; every object still STANDARD → non-compliant.
- **Mixed** current class = objects in more than one class from an existing rule; monthly cost is the sum of per-class costs from Storage Lens, not size × STANDARD price.
- Policy compliant: `Yes` = rule matches the Tiering & Retention Policy for its data class; `No` = no rule or rule does not match; `Exempt` = data class exempt from lifecycle policy.
- EU bucket priced at us-east-1 list, as every other bucket (§5).

### Project Tidewater (§10)
- Goal: reduce S3 spend **45% by the end of Q4** (FY26), measured as steady-state monthly S3 cost at the price sheet, against the August 2026 snapshot baseline (total S3 55,351.50 / month).
- Scope: lifecycle remediation — bring every non-compliant bucket in line with the Tiering & Retention Policy. Exempt buckets out of scope.
- Savings count only once a rule is live, at steady state (§6).

## Storage Architecture & Service Ownership

Source: [company-docs/storage-service-ownership.md](company-docs/storage-service-ownership.md)

### Teams and storage approvers (§4)
| Team | Handle | Storage approver | On-call rotation |
|---|---|---|---|
| Platform | platform-core | @dana.whitfield | platform-core-primary |
| Data Infrastructure | data-infra | @priya.raman | data-infra-primary |
| Mobile | mobile-apps | @marcus.lindqvist | mobile-apps-primary |
| Forecasting | forecasting | @tomas.okafor | forecasting-primary |
| Billing | billing-eng | @grace.adeyemi | billing-eng-primary |
| Integrations | integrations | @leo.brandt | integrations-primary |
| Routing | routing | @sofia.marchetti | routing-primary |

### Service tiers (§3)
| Tier | Definition | Availability SLO | Change window |
|---|---|---|---|
| Tier-1 | Customer-facing / synchronous path | 99.95% | Tue-Thu, outside 06:00-10:00 ET peak; freeze during peak season |
| Tier-2 | Internal production, business-critical, no external synchronous block | 99.9% | Any weekday |
| Tier-3 | Batch / offline | Best effort | Any time |

Service tiers are about the service, not the data. A bucket read by several services inherits the strictest tier among its readers.

### Services and bucket access (§5)
| Service | Owning team | Tier | Writes | Reads |
|---|---|---|---|---|
| telematics-ingest | Data Infrastructure | Tier-2 | kst-telemetry-raw-prod, kst-telemetry-raw-eu | - |
| replay-api | Data Infrastructure | Tier-1 | - | kst-telemetry-raw-prod |
| eta-trainer | Forecasting | Tier-3 | - | kst-telemetry-raw-prod, kst-telemetry-raw-eu, kst-ml-snapshots |
| feature-store | Forecasting | Tier-2 | kst-ml-snapshots | kst-ml-snapshots |
| pod-service | Mobile | Tier-1 | kst-pod-images-prod | kst-pod-images-prod |
| claims-portal | Integrations | Tier-1 | - | kst-pod-images-prod |
| log-shipper | Platform | Tier-2 | kst-app-logs-prod | - |
| logsearch | Platform | Tier-2 | - | kst-app-logs-prod |
| billing-core | Billing | Tier-1 | kst-invoices-archive | kst-invoices-archive |
| pgbackup | Platform | Tier-2 | kst-db-backups-prod | kst-db-backups-prod |
| routing-engine | Routing | Tier-1 | kst-route-cache | kst-route-cache |
| edi-gateway | Integrations | Tier-1 | kst-carrier-edi-inbox | kst-carrier-edi-inbox |
| helpdesk-bridge | Integrations | Tier-2 | kst-support-attachments | kst-support-attachments |
| analytics-exporter | Data Infrastructure | Tier-3 | kst-analytics-exports | - |
| web-frontend | Platform | Tier-1 | - | kst-web-static (via CDN) |

Note: kst-telemetry-raw-eu is NOT read by replay-api; only eta-trainer reads it.

### Bucket owners (§6)
| Bucket | Owning team |
|---|---|
| kst-telemetry-raw-prod | Data Infrastructure |
| kst-telemetry-raw-eu | Data Infrastructure |
| kst-pod-images-prod | Mobile |
| kst-app-logs-prod | Platform |
| kst-ml-snapshots | Forecasting |
| kst-support-attachments | Integrations |
| kst-invoices-archive | Billing |
| kst-db-backups-prod | Platform |
| kst-route-cache | Routing |
| kst-carrier-edi-inbox | Integrations |
| kst-analytics-exports | Data Infrastructure |
| kst-web-static | Platform |

Each production bucket has exactly one owning team, accountable for its lifecycle configuration. Where a bucket's owning team differs from the team that owns a reading service, the reading team must be consulted on changes affecting read latency or availability. Consultation is not approval: the owning team's storage approver makes the call.

### Bucket protection, deletion and access (§8.2, §8.3, §9)
- All production buckets have versioning enabled.
- Object Lock (governance mode) is enabled on kst-invoices-archive and kst-db-backups-prod.
- Cross-region replication is not configured for any production bucket.
- Deletion of a bucket, or of more than 1% of a bucket's objects outside a lifecycle rule, requires the owning team's storage approver *and* a Data Infrastructure approver.
- Bucket policies on all production buckets except kst-web-static deny requests that do not come through an approved VPC endpoint (`aws:SourceVpce`).
- kst-telemetry-raw-eu: bucket policy denies access from outside eu-central-1 except for the telematics-ingest and eta-trainer roles.

### Lifecycle approval and escalation (§13, §15)
- The storage approver of the bucket's owning team approves a change to a bucket's lifecycle rule. The approver of a reading service's team is consulted but does not approve.
- Lifecycle rule behaving unexpectedly: page data-infra-primary, escalate to the owning team's storage approver, then Head of Infrastructure.
- Storage cost anomaly (daily spend jump above 20%): FinOps Slack alert to owning team, escalate to the owning team's storage approver, then Data Infrastructure manager.

## Storage Tiering & Retention Policy

Source: [company-docs/storage-tiering-policy.md](company-docs/storage-tiering-policy.md)

### Definitions (§3)
- **Storage class**: the AWS S3 storage class backing a tier; tooling and lifecycle rules use storage class names, not tier names.
- **Data class**: a registered category of data with a single retention schedule; every bucket has exactly one.
- **Age**: days since object creation (the S3 object creation date), not days since last access or last modification of the bucket.
- **Expire**: permanent deletion of the object (and, for versioned buckets, its non-current versions) once it reaches the stated age.
- **Override**: a rule in §6 that restricts the schedule for a specific bucket, regardless of its data class.
- **Tier-1 service**: customer-facing or revenue-critical, with a synchronous read path and a paging on-call.
- **Policy compliant**: a bucket whose lifecycle rule matches this policy, including overrides.

### Storage tiers (§4)
Each tier maps to exactly one S3 storage class. Do not use any other S3 storage class (e.g. `ONEZONE_IA`, `INTELLIGENT_TIERING`, `GLACIER` Flexible Retrieval) without an approved exception.

| Tier | Storage class | Retrieval | Min storage duration | Min billable object size |
|---|---|---|---|---|
| Hot | STANDARD | ms | none | none |
| Warm | STANDARD_IA | ms | 30 days | 128 KB |
| Cold | GLACIER_IR | ms | 90 days | 128 KB |
| Frozen | DEEP_ARCHIVE | 12-48 h | 180 days | 40 KB overhead |

- Hot, Warm and Cold serve reads in milliseconds; Frozen does not serve reads (restore takes 12-48 h).
- Min storage duration: an object deleted or transitioned out earlier is billed as if it had stayed the full duration.
- Min billable object size: objects <128 KB in Warm or Cold are billed as 128 KB; Frozen adds ~40 KB per-object overhead.

### Data class schedule (§5)
Ages are days since object creation. `30-90` = in that tier from day 30 until day 90. `-` = tier skipped. `all` = stays in that tier for its entire life. Expire = age at which the object is deleted.

| Data class | Hot | Warm | Cold | Frozen | Expire |
|---|---|---|---|---|---|
| telemetry-raw | 0-30 | 30-90 | 90-365 | >365 | 1095 |
| pod-images | 0-90 | 90-365 | >365 | not permitted | 2555 |
| app-logs | 0-30 | 30-90 | - | - | 90 |
| ml-training-snapshots | 0-30 | - | 30-365 | >365 | 730 |
| support-attachments | 0-30 | 30-365 | >365 | not permitted | 1825 |
| invoices | 0-90 | - | >90 | not permitted (7-year statutory retention) | none (manual, Legal) |
| db-backups | 0-3 | 3-35 | - | - | 35 |
| edi-documents | all | - | - | - | 365 |
| ephemeral-cache | all | - | - | - | 7 |
| scratch | all | - | - | - | 30 |
| static-assets | exempt from lifecycle policy | | | | |

- The schedule is the default for the data class; overrides (§6) can remove tiers for a particular bucket, never add.
- `not permitted` in the Frozen column is a hard cap for that data class.
- `static-assets` (CDN origin content, web bundles, email templates) is exempt from lifecycle policy entirely; do not add lifecycle rules to exempt buckets.
- `invoices` have no automatic expiry; deletion after statutory retention is manual, Legal-owned.

### Overrides (§6)
Apply every override that matches. When overrides and the schedule disagree, the more restrictive result wins (fewer tiers, shallower deepest tier). Overrides only ever remove transitions; they never change the Expire value. Overrides are evaluated per bucket, not per data class.

**6.1 Small objects (<128 KB)** — If a bucket's average object size is below 128 KB, it gets no Warm, Cold or Frozen transitions; objects stay Hot until they expire. Expiry still applies as per the schedule. Average object size per bucket is published on **Storage Cost Dashboard & Bucket Inventory**.

**6.2 Tier-1 readers — no Frozen** — If any Tier-1 service reads a bucket, Frozen is not permitted; the deepest tier is Cold. Applies even if the Tier-1 service reads the bucket rarely, and even if it is not the bucket's writer or owner. Service tiers and which services read which buckets are on the **Storage Architecture & Service Ownership** page; check it before deciding whether a bucket may go to Frozen.

**6.3 Statutory retention (invoices)** — Invoices must never go to Frozen within the 7-year retention period.

**6.4 Data-class caps** — Where the schedule says "not permitted" for Frozen, that is a cap. The data class's deepest tier is the last tier before Frozen in its row. Caps can only be lifted by a schedule change, not by an exception.

### Exceptions (§12)
Time-boxed: maximum 12 months, renewable once. An exception cannot:
- lift a data-class cap (requires a schedule change);
- allow Frozen for a bucket read by a Tier-1 service;
- shorten statutory retention;
- override a legal hold.

A bucket not tiered all the way to Frozen because of an override does not need an exception. How that reason is recorded during a migration is covered in **Runbook: Lifecycle Migrations with blobctl**.
