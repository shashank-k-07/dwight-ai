# Storage cost reduction: initiative doc

Written by Dwight for Agents working on Storage cost reduction. 10 of 11 Sessions read the same 4 docs to get started (about 23,892 tokens each time). **This doc replaces those 4 source docs for Storage cost reduction work.** It keeps every rule, table and value those Sessions needed, copied exactly from the sources. Work from this doc; open a source doc only if a value you need is missing here.

Sources (for provenance): [Runbook: Lifecycle Migrations with blobctl](company-docs/blobctl-migration-runbook.md), [Storage Cost Dashboard & Bucket Inventory](company-docs/storage-cost-dashboard.md), [Storage Architecture & Service Ownership](company-docs/storage-service-ownership.md), [Storage Tiering & Retention Policy](company-docs/storage-tiering-policy.md)

## Runbook: Lifecycle Migrations with blobctl

Source: [company-docs/blobctl-migration-runbook.md](company-docs/blobctl-migration-runbook.md)

### Scope: which buckets are in play (§3)
- In scope: dashboard **"Policy compliant" = "No"**. "Yes" = leave alone. "Exempt" = never touched, even if expensive.

### Pre-flight checklist (§4)
- Bucket in scope; data class + current lifecycle rule from the cost dashboard; owning team, its handle and storage approver; which services read the bucket and their service tiers; average object size.
- Target schedule from the Storage Tiering & Retention Policy, after applying every override.
- Change ticket `CHG-` in the `STORCHG` queue with bucket, target schedule, planned exception code.
- Current date not inside a change freeze (§8).

### blobctl and change flow (§2)
- blobctl 1.9, repo `kestrel/blobctl`, installed at `bin/blobctl`. Owner: Data Infrastructure / Storage on-call (`data-infra-primary`).
- All changes land in the **staging control plane first**; nothing writes directly to production. Approved staging rules are promoted by the weekly promotion job (Wednesdays 14:00 ET, run by Storage on-call).
- Flow: plan → apply → status → promotion → verification.

### Transition and expiry syntax (§5.1)
- `--transition <days>:<STORAGE_CLASS>` — days since object creation; ascending order; S3 storage class name (e.g. `STANDARD_IA`), not Kestrel tier name (`Warm`, `Cold` rejected); objects start in `STANDARD`, so never transition to `STANDARD`; omit tiers an override removes.
- `--expire <days>` — days since creation; omit only if the data class has no expiry.

### Rule id convention (§5.2)
- `<owning-team-handle>-<bucket name without the "kst-" prefix>-v<N>`
- Handle = owning team's handle, not the writer/reader team's.
- `N` = version in the bucket's current lifecycle rule + 1, or 1 if none. An expiry-only rule counts as a current rule.
- New rule replaces the old one; do not delete the old rule separately.

### Exception codes (§5.3)
| Code | Meaning |
|---|---|
| `NONE` | Tiered all the way to Frozen |
| `STATUTORY_RETENTION` | Statutory retention prevents Frozen |
| `TIER1_READER` | Tier-1 service reads bucket; Frozen not permitted |
| `DATA_CLASS_CAP` | Data class schedule caps below Frozen |
| `SMALL_OBJECTS` | Average object size too small for archive tiers |

If more than one applies, record the first in this precedence order (one code only, never a comma-separated list):
1. `STATUTORY_RETENTION` 2. `TIER1_READER` 3. `DATA_CLASS_CAP` 4. `SMALL_OBJECTS`

### Running the migration (§6)
Plan (dry run; validates the rule, prints the resulting schedule, records a plan against the rule id):
```
blobctl plan --bucket s3://kst-telemetry-raw-eu --rule-id data-infra-telemetry-raw-eu-v1 --transition 30:STANDARD_IA --transition 90:GLACIER_IR --transition 365:DEEP_ARCHIVE --expire 1095
```
Note: Sessions found blobctl requires the bare bucket name (`kst-telemetry-raw-eu`), not the `s3://` URI form, which is rejected with `E_BADREF` (1.9 and 2.x).

The plan output echoes the bucket, rule id, each transition and the expiry; if any differs from the change ticket, fix and re-plan. Re-planning the same rule id overwrites the earlier plan.

Apply (requires a recorded plan for the same rule id):
```
blobctl apply --rule-id <rule-id> --change <CHG-number> --approver <@handle of owning team's storage approver>
```
- `--approver` = owning team's storage approver, not your manager, the Tidewater lead, or the ticket reviewer.

Status: `blobctl status` lists recorded plans and applied rules (columns: RULE ID, BUCKET, STATE, CHANGE, APPROVER). `planned` = plan recorded, not applied; `applied` = staged, awaiting the Wednesday promotion job. Then update the change ticket with the final rule id, the exception code, a paste of the relevant `blobctl status` lines, and the expected promotion Wednesday.

### Change windows and freeze calendar (§8)
- Promotion job: Wednesdays 14:00 ET. Applied and approved by Wed 12:00 ET is normally picked up that week.
| Freeze | When | Scope |
|---|---|---|
| Month-end close | Last 3 business days of month through 2nd business day of next | Buckets owned by or read by Billing (staging applies too) |
| Peak season | Monday before US Thanksgiving through Jan 5 | All production storage changes except break-glass |
| Company holidays | Kestrel observed holidays | No promotion job; next Wednesday picks up |

Do not plan Billing work in the last week of the month.

### Verification (§10)
- Day 1: `blobctl status` shows promoted; S3 console Management tab lists exactly one rule with the new rule id; CloudWatch `NumberOfObjects` and `BucketSizeBytes` (StorageType `StandardStorage`) flat.
- Day 3-5: `BucketSizeBytes` for target storage types (e.g. `StandardIAStorage`, `GlacierInstantRetrievalStorage`) growing, `StandardStorage` falling; watch owning team's dashboards for `403`/`InvalidObjectState` spikes.
- Day 14: S3 Storage Lens dashboard `kestrel-org-default` matches the plan; close the ticket.

### Known issues (§14)
- Re-planning a rule id overwrites the earlier plan without warning.
- `blobctl status` paging can swallow the last line; pipe through `cat` or run non-interactively.

## Storage Cost Dashboard & Bucket Inventory

Source: [company-docs/storage-cost-dashboard.md](company-docs/storage-cost-dashboard.md)

### Price sheet (§5)
USD per GB-month. **1 TB = 1,000 GB.** eu-central-1 is normalised to us-east-1 list prices, so EU buckets use the same numbers as US buckets.

| Storage class | USD per GB-month |
|---|---|
| STANDARD | 0.023 |
| STANDARD_IA | 0.0125 |
| GLACIER_IR | 0.004 |
| DEEP_ARCHIVE | 0.00099 |

Storage only. Request, transition and retrieval fees are excluded (measured at under 2% of S3 cost).

### Steady-state savings method (§6)
1. For each age band (0-30d, 30-90d, 90-365d, >365d): band size in TB × 1000 × price of the storage class the policy puts that band in.
2. Bands older than the expiry age are deleted, so they cost 0.
3. Sum the bands = **monthly cost after**.
4. Ignore request, transition and retrieval fees.
5. **Saving = current monthly cost − cost after.**
6. Round to cents. Keep full precision through the calculation; round only the final figures.

"Steady state" = the saving once the rule has run long enough that every object sits in its target class, not the first month after a change.

### Bucket inventory — non-compliant buckets (§7)
August 2026 snapshot, taken 2026-09-01. Age bands in TB. Monthly cost is list-price-equivalent at the price sheet above.

| Bucket | Writer service | Data class | Avg object | 0-30d | 30-90d | 90-365d | >365d | Lifecycle rule | Policy compliant | Monthly cost USD |
|---|---|---|---|---|---|---|---|---|---|---|
| s3://kst-telemetry-raw-prod | telematics-ingest | telemetry-raw | 2.4 MB | 60 | 110 | 380 | 270 | none | No | 18,860.00 |
| s3://kst-telemetry-raw-eu | telematics-ingest | telemetry-raw | 2.4 MB | 15 | 30 | 95 | 70 | none | No | 4,830.00 |
| s3://kst-pod-images-prod | pod-service | pod-images | 1.1 MB | 25 | 40 | 175 | 300 | mobile-apps-pod-images-prod-v1 (expiry only) | No | 12,420.00 |
| s3://kst-app-logs-prod | log-shipper | app-logs | 38 KB | 95 | 170 | 45 | 0 | none | No | 7,130.00 |
| s3://kst-ml-snapshots | feature-store | ml-training-snapshots | 480 MB | 20 | 35 | 105 | 100 | none | No | 5,980.00 |
| s3://kst-support-attachments | helpdesk-bridge | support-attachments | 850 KB | 4 | 6 | 12 | 14 | none | No | 828.00 |

**Total S3: 55,351.50 / month** (August 2026 snapshot, taken 2026-09-01).

Notes:
- **s3://kst-pod-images-prod** has rule `mobile-apps-pod-images-prod-v1`, but it is **expiry-only**: it deletes objects at the end of their retention and has no storage class transitions. Every object is still in STANDARD, so the bucket is non-compliant despite having a rule.
- **Policy compliant**: `Yes` = the lifecycle rule matches the Tiering & Retention Policy for its data class; `No` = no rule, or the rule does not match; `Exempt` = the data class is exempt from lifecycle policy.
- The EU bucket is priced at us-east-1 list, as for every other bucket.

### Project Tidewater (§10)
**Goal:** reduce S3 spend by **45% by the end of Q4** (FY26), measured as steady-state monthly S3 cost at the price sheet, against the August 2026 snapshot baseline.

**Scope:** lifecycle remediation — bringing every non-compliant bucket in line with the Tiering & Retention Policy. Exempt buckets are out of scope.

**WS1 — Lifecycle remediation of non-compliant buckets:** buckets marked `No` in §7. Status: In progress. Changes go through the migration runbook. Savings measured with the §6 method once rules are applied.

**Non-compliance summary (§13):** six buckets are non-compliant and they are most of the S3 spend; five have no lifecycle rule, one (proof-of-delivery images, s3://kst-pod-images-prod) has an expiry-only rule. WS1 works through all six this quarter.

## Storage Architecture & Service Ownership

Source: [company-docs/storage-service-ownership.md](company-docs/storage-service-ownership.md)

### Service tiers (§3)

| Service tier | Definition |
|---|---|
| Tier-1 | Customer-facing / synchronous path. A customer, driver or carrier is waiting on the response in real time. |
| Tier-2 | Internal production. Business-critical, but no external party is blocked synchronously; backlogs can be caught up. |
| Tier-3 | Batch / offline. Scheduled or ad-hoc jobs; a missed run is re-run. |

A bucket read by several services effectively inherits the strictest tier among its readers.

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

### Services, tiers and bucket readers (§5)

| Service | Owning team | Tier | Writes | Reads |
|---|---|---|---|---|
| telematics-ingest | Data Infrastructure | Tier-2 | kst-telemetry-raw-prod, kst-telemetry-raw-eu | - |
| replay-api | Data Infrastructure | Tier-1 | - | kst-telemetry-raw-prod (trip replay for customer disputes; synchronous) |
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

Note: the EU telemetry bucket kst-telemetry-raw-eu is NOT read by replay-api (EU replay was decommissioned in 2025); only eta-trainer reads it.

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

The owning team's storage approver approves lifecycle changes. Where a bucket's owning team differs from the team that owns a reading service, the reading team must be consulted on any change that could affect read latency or availability; consultation is not approval.

### Tagging standard (§10)

| Tag key | Example value | Meaning |
|---|---|---|
| `kestrel:team` | `mobile-apps` | Owning team handle from section 4 |
| `kestrel:service` | `pod-service` | Primary writing service from section 5 |
| `kestrel:data-class` | `pod-images` | Data class as defined in the Storage Tiering Policy |
| `kestrel:env` | `prod` | One of `prod`, `staging`, `sandbox` |
| `kestrel:cost-center` | `CC-4120` | Finance cost center of the owning team |
| `kestrel:pii` | `true` | Whether the bucket may contain personal data |
| `kestrel:residency` | `us` | `us` or `eu`; must match the bucket's region |

### Access, deletion and residency constraints (§8.2, §8.3)

- Deletion of a bucket, or of more than 1% of a bucket's objects outside a lifecycle rule, requires the owning team's storage approver *and* a Data Infrastructure approver.
- Bucket policies grant access to roles, never to users. Write access only to the writing service in §5; read access only to the listed readers.
- EU data stays in eu-central-1. The EU bucket policy denies access from outside eu-central-1 except for the `telematics-ingest` and `eta-trainer` roles.

### S3 protection state (§9)

- All production buckets have versioning enabled and rely on S3's regional durability.
- Object Lock (governance mode) is enabled on `kst-invoices-archive` and `kst-db-backups-prod`.
- Cross-region replication is not configured for any production bucket today.

### Escalation for lifecycle work (§13)

| Situation | First page | Escalate to | Then |
|---|---|---|---|
| Lifecycle rule behaving unexpectedly | data-infra-primary | Owning team's storage approver | Head of Infrastructure |

## Storage Tiering & Retention Policy

Source: [company-docs/storage-tiering-policy.md](company-docs/storage-tiering-policy.md)

### Scope & definitions (§1, §3)

- In scope: every S3 bucket in every Kestrel-owned AWS account, in both `us-east-1` (primary) and `eu-central-1` (EU), including buckets created by vendors on our behalf.
- Age = days since object creation (the S3 object creation date), not days since last access or last modification.
- Policy compliant = a bucket whose lifecycle rule matches this policy, including overrides.
- Tier-1 service = customer-facing or revenue-critical, with a synchronous read path and a paging on-call.

### Storage tiers (§4)

| Kestrel tier | Storage class | Retrieval | Min storage duration | Min billable object size |
|---|---|---|---|---|
| Hot | STANDARD | ms | none | none |
| Warm | STANDARD_IA | ms | 30 days | 128 KB |
| Cold | GLACIER_IR | ms | 90 days | 128 KB |
| Frozen | DEEP_ARCHIVE | 12-48 h | 180 days | 40 KB overhead |

- Do not use any other S3 storage class (e.g. `ONEZONE_IA`, `INTELLIGENT_TIERING`, `GLACIER` Flexible Retrieval) without an approved exception.
- Frozen does not serve reads; an object must be restored first (12-48 h).
- An object deleted or transitioned out before the minimum storage duration is billed as if it had stayed the full duration.
- Warm/Cold bill objects smaller than 128 KB as 128 KB; Frozen adds ~40 KB per-object overhead.

### Data class schedule (§5)

Ages are days since object creation. A range such as `30-90` means the object is in that tier from day 30 until day 90; `>365` means from day 365 onwards. `-` = tier skipped. `all` = stays in that tier for its entire life. Expire = age at which the object is deleted.

| Data class | Hot | Warm | Cold | Frozen | Expire |
|---|---|---|---|---|---|
| telemetry-raw | 0-30 | 30-90 | 90-365 | >365 | 1095 |
| pod-images (proof-of-delivery photos) | 0-90 | 90-365 | >365 | not permitted | 2555 |
| app-logs | 0-30 | 30-90 | - | - | 90 |
| ml-training-snapshots | 0-30 | - | 30-365 | >365 | 730 |
| support-attachments | 0-30 | 30-365 | >365 | not permitted | 1825 |
| invoices | 0-90 | - | >90 | not permitted (7-year statutory retention) | none (manual, Legal) |
| db-backups | 0-3 | 3-35 | - | - | 35 |
| edi-documents | all | - | - | - | 365 |
| ephemeral-cache | all | - | - | - | 7 |
| scratch | all | - | - | - | 30 |
| static-assets | exempt from lifecycle policy | | | | |

- The schedule is the default for the data class; overrides only remove tiers, never add.
- "not permitted" in the Frozen column is a hard cap for that data class.
- `static-assets` is exempt: do not add lifecycle rules to exempt buckets.
- Invoices have no automatic expiry; deletion after the 7-year statutory retention period is manual and Legal-owned.

### Overrides (§6)

Apply every override that matches. When overrides and the schedule disagree, the more restrictive result wins (fewer tiers, shallower deepest tier). Overrides only ever remove transitions; they never change the Expire value. Overrides are evaluated per bucket, not per data class.

#### Small objects (<128 KB) (§6.1)
If a bucket's average object size is below 128 KB, it gets no Warm, Cold or Frozen transitions; objects stay Hot until they expire. Expiry still applies as per the schedule. (Average object size per bucket is published on Storage Cost Dashboard & Bucket Inventory.)

#### Tier-1 readers — no Frozen (§6.2)
If any Tier-1 service reads a bucket, Frozen is not permitted for that bucket; the deepest tier is Cold. Applies even if the Tier-1 service reads the bucket rarely, and even if it is not the bucket's writer or owner.

#### Statutory retention (invoices) (§6.3)
Invoices must never go to Frozen within the 7-year retention period; they must remain retrievable in milliseconds for audit and tax enquiries.

#### Data-class caps (§6.4)
Where the schedule says "not permitted" for Frozen, that is a cap: the data class's deepest tier is the last tier before Frozen in its row, regardless of bucket-level considerations. Caps can only be lifted by a schedule change, not by an exception.

### Exceptions (§12)

- Time-boxed: maximum 12 months, renewable once.
- An exception cannot: lift a data-class cap; allow Frozen for a bucket read by a Tier-1 service; shorten statutory retention; override a legal hold.
- A bucket not tiered all the way to Frozen because of an override does not need an exception.

### Encryption (§8)

- Tiering does not change encryption; objects keep their encryption when they transition between storage classes. Do not re-encrypt objects as part of a lifecycle change.
