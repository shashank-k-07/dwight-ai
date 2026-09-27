# Storage Architecture & Service Ownership

| Field | Value |
|---|---|
| Doc id | `storage-service-ownership` |
| Space | Perch / Engineering / Platform |
| Owner | Platform + Data Infrastructure |
| Last reviewed | 2026-08-21 |

> **Info panel.** This page is the source of truth for *who owns what* in Kestrel's storage layer: which team owns each S3 bucket, which services write and read each bucket, and what service tier each service runs at. If another Perch page disagrees with this one about ownership or service tier, this page wins; please raise a correction in `#storage-help`.

---

## 1. Purpose and scope

Kestrel Logistics runs its production workloads on AWS, with the primary region in us-east-1 and an EU footprint in eu-central-1. This page answers "who do I ask about this bucket?"

**In scope**

- Production S3 buckets named `kst-*` in the kestrel-prod and kestrel-data accounts.
- The services that write to or read from those buckets, and the team that owns each service.
- The service tier of each service (see section 3).
- The main non-S3 datastores, listed for context so that on-call engineers can find the right team quickly.

**Out of scope**

- Storage classes, lifecycle schedules and retention periods. These are defined in the *Storage Tiering Policy* page, owned by Data Infrastructure.
- Bucket sizes, spend and savings figures. These are on the *Storage Cost Dashboard*, owned by FinOps (Finance).
- The mechanics of changing a lifecycle rule. See the *Storage Lifecycle Migration Runbook*.
- Staging and sandbox buckets.

---

## 2. Architecture overview

Kestrel's storage layer is organised around a handful of high-volume data flows. The diagram below shows the main producers and consumers. It omits internal queues, retries and sidecars.

```
                        +---------------------------+
  Truck telematics      |  Kinesis Data Streams     |
  units (ELD / GPS) --->|  telematics-raw (us-east-1)|
  via IoT Core          |  telematics-raw-eu        |
                        |  (eu-central-1)           |
                        +-------------+-------------+
                                      |
                                      v
                          +-----------------------+
                          |  telematics-ingest    |  (Data Infrastructure, Tier-2)
                          +-----+-----------+-----+
                                |           |
                                v           v
                 kst-telemetry-raw-prod   kst-telemetry-raw-eu
                     (us-east-1)            (eu-central-1)
                       |      |                  |
          +------------+      +---------+        |
          v                             v        v
   +-------------+                  +--------------+
   | replay-api  |                  | eta-trainer  |  (Forecasting, Tier-3)
   | (Tier-1)    |                  +------+-------+
   +------+------+                         |
          |                                v
          v                          kst-ml-snapshots <---> feature-store
   Customer portal:                                         (Forecasting, Tier-2)
   trip replay for
   disputes


  Mobile driver app                 +--------------+
  (iOS / Android)  -- POD photo --->| pod-service  |---> kst-pod-images-prod
                                    | (Mobile,     |         |
                                    |  Tier-1)     |         v
                                    +--------------+   claims-portal
                                                       (Integrations, Tier-1)

  All services --stdout--> log-shipper ---> kst-app-logs-prod ---> logsearch
                           (Platform)                             (Platform)

  Carrier EDI (AS2/SFTP) ---> edi-gateway <---> kst-carrier-edi-inbox
  Zendesk webhooks -------> helpdesk-bridge <---> kst-support-attachments
  billing-core <---> kst-invoices-archive
  routing-engine <---> kst-route-cache
  Aurora clusters ---> pgbackup <---> kst-db-backups-prod
  analytics-exporter ---> kst-analytics-exports ---> (downloaded by analysts)
  kst-web-static ---> CloudFront ---> web-frontend (browser)
```

### 2.1 Telematics

Every truck in the Kestrel network carries an electronic logging device that sends position, speed and hours-of-service events every few seconds. Devices publish to AWS IoT Core, which fans out into Kinesis Data Streams. There is one stream per region; EU-registered fleets publish to eu-central-1 to meet data residency commitments in our EU carrier contracts.

`telematics-ingest` consumes both streams, batches events into compressed Parquet files of roughly 2 to 3 MB, and writes them to the regional telemetry bucket.

The US telemetry bucket has two main consumers: `replay-api`, which serves trip replay in the customer portal when a shipper disputes a delivery time, and `eta-trainer`, which uses the history to retrain the ETA models. The EU bucket is consumed only by `eta-trainer` (see the note in section 5 and the history in section 14.1).

### 2.2 Proof of delivery

Drivers photograph each delivery (and any damage) in the Kestrel Driver app. The app uploads to `pod-service` over a pre-signed flow, and `pod-service` stores the photo in `kst-pod-images-prod` together with a metadata record in the `pod` Aurora cluster. `claims-portal` reads the photos when a shipper or consignee opens a damage or non-delivery claim.

### 2.3 Logs, backups and the rest

Application logs from every service go through `log-shipper` (a Fluent Bit fleet plus an aggregation tier) into `kst-app-logs-prod`. `logsearch` indexes recent logs into OpenSearch for engineers and reads older partitions directly from S3 on demand. The remaining buckets each belong to a single service (section 5).

---

## 3. Service tiers

Every production service at Kestrel is assigned a service tier. The tier drives SLOs, on-call expectations, change windows and DR targets. Other policies (including the Storage Tiering Policy) refer to these service tiers, so they must be kept accurate on this page.

| Service tier | Definition | Availability SLO | On-call expectation | Change window |
|---|---|---|---|---|
| Tier-1 | Customer-facing / synchronous path. A customer, driver or carrier is waiting on the response in real time. | 99.95% | 24x7 paging, 5-minute acknowledgement | Tue-Thu, outside 06:00-10:00 ET peak; freeze during peak season |
| Tier-2 | Internal production. Business-critical, but no external party is blocked synchronously; backlogs can be caught up. | 99.9% | 24x7 paging, 15-minute acknowledgement | Any weekday |
| Tier-3 | Batch / offline. Scheduled or ad-hoc jobs; a missed run is re-run. | Best effort | Business hours only | Any time |

Service tiers are about the *service*, not about the data. A bucket read by several services effectively inherits the strictest tier among its readers when you are reasoning about latency and availability.

**Assigning or changing a tier.** The owning team proposes the tier in the service's design review. The Platform architecture group confirms it. Promoting a service to Tier-1 requires a production readiness review (PRR) that covers runbooks, dashboards and a tested failover.

---

## 4. Teams

The table below lists every team that owns at least one production service or bucket. The **storage approver** is the named individual who approves storage changes (lifecycle, retention, access policy, deletion) for buckets owned by that team.

| Team | Business Function | Handle | Storage approver | On-call rotation |
|---|---|---|---|---|
| Platform | Engineering | platform-core | @dana.whitfield | platform-core-primary |
| Data Infrastructure | Engineering | data-infra | @priya.raman | data-infra-primary |
| Mobile | Engineering | mobile-apps | @marcus.lindqvist | mobile-apps-primary |
| Forecasting | Engineering | forecasting | @tomas.okafor | forecasting-primary |
| Billing | Engineering | billing-eng | @grace.adeyemi | billing-eng-primary |
| Integrations | Engineering | integrations | @leo.brandt | integrations-primary |
| Routing | Engineering | routing | @sofia.marchetti | routing-primary |

The team handle is used for Slack user groups (`@platform-core` and so on), GitHub teams, PagerDuty service ownership and the `kestrel:team` tag (section 10). FinOps sits in Finance and does not own buckets; it consumes this page for cost allocation.

---

## 5. Services

This table lists every production service that writes to or reads from a `kst-*` bucket. A dash means the service does not write (or does not read) any bucket.

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

> **Note:** the EU telemetry bucket kst-telemetry-raw-eu is NOT read by replay-api (EU replay was decommissioned in 2025, see note); only eta-trainer reads it.
>
> The decommissioning is described in section 14.1.

**Keeping this table accurate.** Reader and writer lists are validated monthly against S3 server access logs and CloudTrail data events by a Data Infrastructure job. If you add a new reader, update this page *before* the IAM grant is merged.

---

## 6. Bucket owners

Each production bucket has exactly one owning team. The owning team is accountable for the bucket's access policy, lifecycle configuration, cost and data handling, and its storage approver (section 4) signs off changes to it.

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

Where a bucket's owning team differs from the team that owns a reading service (for example, `claims-portal` is owned by Integrations but reads a Mobile-owned bucket), the reading team must be consulted on any change that could affect read latency or availability. Consultation is not the same as approval: the owning team's storage approver makes the call.

---

## 7. Non-S3 datastores

These are listed so that on-call engineers can find owners quickly. They are not governed by the storage tiering programme.

| Datastore | Engine | Region | Owning team | Main consumers | Notes |
|---|---|---|---|---|---|
| shipments-main | Aurora PostgreSQL 15 | us-east-1 | Platform | Shipment API, routing-engine, billing-core | Writer plus 3 readers; the largest cluster |
| billing | Aurora PostgreSQL 15 | us-east-1 | Billing | billing-core | PCI scope; separate KMS key |
| pod | Aurora PostgreSQL 14 | us-east-1 | Mobile | pod-service, claims-portal | Upgrade to 15 planned for Q4 |
| route-sessions | ElastiCache Redis 7 (cluster mode) | us-east-1 | Routing | routing-engine | Holds live route state; not persisted |
| logsearch | OpenSearch 2.x | us-east-1 | Platform | logsearch | Holds roughly 14 days of indexed logs |
| feature-online | DynamoDB | us-east-1 | Forecasting | feature-store (online serving) | On-demand capacity |

All Aurora clusters use automated snapshots with 7-day retention. On top of that, `pgbackup` takes nightly logical dumps into `kst-db-backups-prod` (section 9).

---

## 8. Accounts, IAM and network layout

### 8.1 AWS accounts

Kestrel uses AWS Organizations with a small number of workload accounts. Production S3 buckets live in two of them.

| Account | Purpose | Production buckets hosted |
|---|---|---|
| kestrel-prod | Customer-facing and internal production services | kst-pod-images-prod, kst-app-logs-prod, kst-support-attachments, kst-invoices-archive, kst-db-backups-prod, kst-route-cache, kst-carrier-edi-inbox, kst-web-static |
| kestrel-data | Data platform, ML and analytics | kst-telemetry-raw-prod, kst-telemetry-raw-eu, kst-ml-snapshots, kst-analytics-exports |
| kestrel-staging | Pre-production copies of all services | None (staging buckets use the `kst-stg-*` prefix) |
| kestrel-security | CloudTrail organisation trail, GuardDuty, Security Hub | None in scope |

### 8.2 IAM model

- Every service runs under its own IAM role (`svc-<service-name>`). Roles are created by the infra-storage Terraform modules and are never shared between services.
- Bucket policies grant access to roles, never to users. Write access is granted only to the writing service listed in section 5. Read access is granted only to the listed readers.
- Cross-account grants name the specific role ARN, never whole accounts.
- Human access to production buckets goes through the `storage-breakglass` role, which requires a ticket number and is limited to one hour.
- Deletion of a bucket, or of more than 1% of a bucket's objects outside a lifecycle rule, requires the owning team's storage approver *and* a Data Infrastructure approver.

### 8.3 Network

- Each production VPC has an S3 gateway endpoint. Bucket policies on all production buckets except `kst-web-static` deny requests that do not come through an approved VPC endpoint (`aws:SourceVpce`).
- `kst-web-static` is served only through CloudFront using Origin Access Control. Direct public access to the bucket is blocked.
- Kinesis, KMS and STS are reached through interface endpoints in every VPC.
- The kestrel-data VPCs peer with kestrel-prod through the shared Transit Gateway. No production data transits the public internet between accounts.
- EU data stays in eu-central-1. The EU bucket has a bucket policy that denies access from outside eu-central-1 except for the `telematics-ingest` and `eta-trainer` roles. `eta-trainer` runs its EU training jobs in eu-central-1 and exports only model artefacts, never raw telemetry.

---

## 9. Disaster recovery and backup

DR targets follow the service tier of the service, not the bucket. Where a bucket supports several services, it is protected to the target of its strictest service.

| Service tier | RPO | RTO | Strategy |
|---|---|---|---|
| Tier-1 | 15 minutes | 1 hour | Multi-AZ everywhere; pre-provisioned standby for stateful components; tested failover every quarter |
| Tier-2 | 4 hours | 8 hours | Multi-AZ; restore from backups or replay from source; failover tested twice a year |
| Tier-3 | 24 hours | 72 hours | Re-run from source data; no dedicated standby |

**S3.** All production buckets have versioning enabled and rely on S3's regional durability. Object Lock (governance mode) is enabled on `kst-invoices-archive` and `kst-db-backups-prod`. Cross-region replication is not configured for any production bucket today.

**Databases.** Aurora automated snapshots (7 days) plus `pgbackup` logical dumps. Restore drills run monthly in kestrel-staging.

**Telemetry.** If `telematics-ingest` is down, Kinesis keeps 7 days of events, so data is not lost as long as ingest recovers within that window.

---

## 10. Tagging standard

Every production bucket must carry the following tags. The infra-storage CI rejects any bucket definition that is missing one, and a nightly AWS Config rule flags drift.

| Tag key | Example value | Meaning |
|---|---|---|
| `kestrel:team` | `mobile-apps` | Owning team handle from section 4 |
| `kestrel:service` | `pod-service` | Primary writing service from section 5 |
| `kestrel:data-class` | `pod-images` | Data class as defined in the Storage Tiering Policy |
| `kestrel:env` | `prod` | One of `prod`, `staging`, `sandbox` |
| `kestrel:cost-center` | `CC-4120` | Finance cost center of the owning team |
| `kestrel:pii` | `true` | Whether the bucket may contain personal data |
| `kestrel:residency` | `us` | `us` or `eu`; must match the bucket's region |

Propose new `kestrel:` tag keys in `#storage-help` before using them.

---

## 11. Requesting a new bucket

1. **Check that you actually need a new bucket.** A new prefix in an existing bucket is often enough.
2. **File a STOR request** in the Perch Service Desk using the *New production bucket* form. You will need the proposed name, owning team, writing service, reading services and their service tiers, data class, region, expected monthly growth and whether it contains PII.
3. **Naming.** Production buckets use `kst-<purpose>[-<qualifier>]`, all lower case, hyphen separated, with no team names in the bucket name (teams change; purposes rarely do). Examples: `kst-pod-images-prod`, `kst-carrier-edi-inbox`.
4. **Approval.** The owning team's storage approver approves the request. Data Infrastructure reviews it for naming, tagging, encryption and data class. Security reviews it if `kestrel:pii` is `true` or the bucket is in eu-central-1.
5. **Provisioning.** Data Infrastructure merges the Terraform change in the infra-storage repository. New buckets are created with versioning, default SSE-KMS encryption, Block Public Access, the VPC endpoint policy and the mandatory tags.
6. **Update this page.** The requester adds rows to sections 5 and 6 in the same week.

Typical turnaround is three working days.

---

## 12. Changing ownership

Ownership changes happen most often during reorgs or when a service is handed over. The process is:

1. The current and receiving teams agree the handover in writing (a comment on a STOR ticket is enough).
2. The receiving team's storage approver accepts ownership on the ticket.
3. Data Infrastructure updates the `kestrel:team` tag and the cost-center tag, and moves PagerDuty service ownership.
4. This page is updated: sections 5 and 6, plus a revision history entry.
5. FinOps is notified so that cost allocation moves at the start of the next month. Mid-month moves are not pro-rated.

Until step 4 is complete, the previous owning team remains accountable. The bucket owners table in section 6 is authoritative.

---

## 13. On-call and escalation matrix

Page the owning team's primary rotation first. If there is no acknowledgement within the time for the affected service's tier (section 3), escalate as shown below.

| Situation | First page | Escalate to | Then |
|---|---|---|---|
| Bucket unavailable or access denied for a Tier-1 reader | Owning team primary rotation | data-infra-primary | Incident Commander rotation (`ic-primary`) |
| Unexpected mass deletion or version purge | data-infra-primary | Owning team primary rotation plus Security on-call | Head of Infrastructure |
| Suspected data exposure (public object, wrong grant) | Security on-call | data-infra-primary | CISO |
| Telemetry ingest lag above 30 minutes | data-infra-primary | platform-core-primary | Incident Commander rotation |
| Storage cost anomaly (daily spend jump above 20%) | FinOps Slack alert to owning team | Owning team's storage approver | Data Infrastructure manager |
| Lifecycle rule behaving unexpectedly | data-infra-primary | Owning team's storage approver | Head of Infrastructure |

Rotation names are the ones in section 4. Secondary rotations follow the pattern `<handle>-secondary`.

---

## 14. Historical notes

### 14.1 EU replay decommissioning (2025)

Until mid-2025, `replay-api` had a regional deployment in eu-central-1 that served trip replay for EU fleets from `kst-telemetry-raw-eu`. Usage was very low (fewer than 40 replay requests a month across all EU customers), and every EU dispute workflow migrated to the export-based evidence pack produced by the Integrations team. The EU deployment of `replay-api` was decommissioned in 2025 after a 90-day notice period to affected customers, and its read grant on the EU bucket was removed.

Since then, `kst-telemetry-raw-eu` has been read only by `eta-trainer`. Engineers sometimes assume from the bucket's name that replay still reads it, because the US bucket is read by `replay-api`. It does not.

### 14.2 Migration from kst-legacy-* buckets (2024)

Before 2024, most production data lived in a set of buckets created in the original single AWS account, all prefixed `kst-legacy-` (for example `kst-legacy-uploads`, `kst-legacy-logs` and `kst-legacy-data`). They mixed data classes and owners and had no consistent tags.

In 2024, Data Infrastructure ran the "Nest" migration. Data was split by purpose into the current `kst-*` buckets, moved into the kestrel-prod and kestrel-data accounts, and tagged to the standard in section 10. The migration completed in November 2024. All `kst-legacy-*` buckets were emptied and deleted in January 2025 after a 60-day read-only period. Any remaining `kst-legacy-*` reference is stale.

---

## 15. FAQ

**Q: Who approves a change to a bucket's lifecycle rule?**
A: The storage approver of the bucket's owning team (sections 4 and 6). The approver of a reading service's team is consulted but does not approve.

**Q: Does the service tier of a writer matter as much as the tier of a reader?**
A: For storage decisions, readers usually matter more. The reader is who waits when an object is slow to retrieve. Check both columns of the services table.

**Q: Where are storage classes and retention periods defined?**
A: In the Storage Tiering Policy. This page only defines *service* tiers, which that policy refers to.

**Q: I am on-call and cannot reach a storage approver. Can I approve on their behalf?**
A: No. Use the delegate listed on the team's Perch home page, or escalate using section 13.

---

## 16. Revision history

| Date | Author | Change |
|---|---|---|
| 2026-08-21 | @priya.raman | Quarterly review. Reconfirmed all service tiers and readers against access logs; no changes. |
| 2026-06-02 | @dana.whitfield | Updated `pod` cluster upgrade plan. |
| 2026-03-14 | @priya.raman | Added `kestrel:residency` tag to the tagging standard. |
| 2026-01-09 | @leo.brandt | `claims-portal` promoted to Tier-1 after PRR; services table updated. |
| 2025-10-20 | @priya.raman | Removed `replay-api` as a reader of `kst-telemetry-raw-eu` following EU replay decommissioning; added section 14.1. |
| 2025-02-03 | @dana.whitfield | Removed remaining `kst-legacy-*` references after bucket deletion. |
| 2024-11-28 | @priya.raman | Page restructured after the Nest migration; bucket owners table added. |
| 2024-04-11 | @dana.whitfield | Page created. |
