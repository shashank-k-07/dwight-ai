# Storage Cost Dashboard & Bucket Inventory

| | |
|---|---|
| **Doc id** | `storage-cost-dashboard` |
| **Space** | Perch > Finance > FinOps > Cloud Cost |
| **Owner** | FinOps (Finance), maintained with Data Infrastructure |
| **Snapshot** | August 2026, taken 2026-09-01 |
| **Status** | Current |
| **Last reviewed** | 2026-09-03 (FinOps monthly review) |

> **Info:** This page is the written companion to the **Storage Cost** Looker dashboard. The figures in the bucket inventory below are frozen at the August 2026 snapshot so that Project Tidewater work can be planned against one set of numbers.

**Related pages**

- *Storage Tiering & Retention Policy*: tiers, how they map to S3 storage classes, the data class schedule, and overrides.
- *Storage Architecture & Service Ownership*: which services read and write each bucket, service tiers, owning teams, and storage approvers.
- *Runbook: Lifecycle Migrations with blobctl*: how lifecycle rules are planned and applied, and how rule ids are named.
- *Project Tidewater: Programme Charter* (Finance space).

This page does not repeat what those pages say.

---

## 1. Opening the dashboard

The dashboard is in Looker under **Shared > Finance > FinOps > Storage Cost**. You need the `looker-finops-viewer` group, which every Kestrel employee in Engineering, Finance and Operations gets automatically through Okta. Contractors must request it through the IT Service Desk (form: *Analytics access > Looker group*).

1. Sign in to Looker via the Okta tile **Looker (Analytics)**.
2. In the left-hand navigation choose **Shared > Finance > FinOps**.
3. Open **Storage Cost**. The default view is the current calendar month to date, all regions, all accounts.
4. Use the filter bar at the top to change **Month**, **Region**, **AWS account**, **Cost center** and **Data class**. Filters apply to every tile except *Programme progress*, which always shows the whole of Tidewater.
5. To see the frozen snapshot that this page is built from, set **Snapshot** to `2026-09-01`. The live view has **Snapshot** set to `latest`.

Tips:

- Clicking a bucket name in any tile drills into the **Bucket detail** look, which shows daily cost and the object-age histogram for that bucket.
- **Download > CSV** on the *Bucket inventory* tile gives the same columns as the table in section 7, plus a few internal columns (account id, KMS key alias, versioning flag).

---

## 2. What each tile means

| Tile | What it shows | Notes |
|---|---|---|
| **S3 spend (month)** | Total S3 storage cost for the selected month, in USD. | Storage only. |
| **Spend by storage class** | Stacked bar of cost by S3 storage class. | Buckets that are "mixed" are split using Storage Lens byte counts per class. |
| **Bucket inventory** | One row per bucket; same columns as section 7. | Sort by *Monthly cost USD* to find the big buckets quickly. |
| **Object age bands** | TB per bucket in the 0-30d, 30-90d, 90-365d and >365d bands. | Age is days since object creation, from Storage Lens and the nightly inventory job. |
| **Policy compliance** | Count and cost of buckets that are compliant, non-compliant, or exempt. | Compliance is evaluated against the Tiering & Retention Policy by the nightly job. |
| **Programme progress** | Tidewater run-rate against target. | Not affected by filters. |
| **Untagged spend** | Cost from resources with no `kestrel:cost-center` tag. | Target is under 1% of total. |

---

## 3. Data sources

The dashboard joins three sources.

**AWS Cost and Usage Report (CUR 2.0).** The CUR is exported hourly by AWS to `s3://kst-finops-cur` in the payer account and loaded into the warehouse table `finops.cur_line_items` by the `cur-loader` Airflow DAG. For this dashboard we use list-price-equivalent cost (see section 5) rather than net amortised cost, so that Tidewater savings are not distorted by discount changes.

**Amazon S3 Storage Lens (advanced metrics).** Storage Lens gives daily per-bucket byte and object counts by storage class, and the average object size. Advanced metrics are enabled at the organisation level. Storage Lens exports land in `s3://kst-finops-storage-lens` and are loaded into `finops.storage_lens_daily`.

**Nightly inventory job (`bucket-inventory-nightly`).** Owned by Data Infrastructure and run in Airflow at 02:30 ET. It reads S3 Inventory reports for every production bucket, computes the object-age bands, reads the current lifecycle configuration, and evaluates policy compliance. Output goes to `finops.bucket_inventory_daily`. This is where the *Lifecycle rule* and *Policy compliant* columns come from.

---

## 4. Refresh schedule and known data lags

| Source | Refresh | Typical lag | Known issues |
|---|---|---|---|
| CUR 2.0 | Hourly export, loaded every 4 hours | 8-24 hours | Previous month can be restated until about the 5th. |
| Storage Lens | Daily | 24-48 hours | Occasionally skips a day; previous day is carried forward. |
| Nightly inventory job | Daily, 02:30 ET | Up to 36 hours | Inventory for buckets over 1 billion objects can arrive a day late. |
| Looker PDT rebuild | Daily, 06:00 ET | n/a | Tiles may mix old and new data before 07:00 ET. |

Snapshots are taken on the 1st of each month at 09:00 ET for the previous calendar month, after the PDT rebuild. FinOps re-checks it on the 6th and re-cuts it if total S3 cost moved by more than 0.5%. The August 2026 snapshot did not need a re-cut.

---

## 5. Price sheet

FinOps uses a fixed price sheet so that savings are comparable across months and regions. Prices are USD per GB-month, and **1 TB = 1,000 GB**. FinOps normalises eu-central-1 to us-east-1 list prices, so EU buckets are priced with the same numbers as US buckets.

| Storage class | USD per GB-month |
|---|---|
| STANDARD | 0.023 |
| STANDARD_IA | 0.0125 |
| GLACIER_IR | 0.004 |
| DEEP_ARCHIVE | 0.00099 |

The price sheet covers storage only. Request, transition and retrieval fees are left out; FinOps has measured them at under 2% of S3 cost.

---

## 6. Steady-state savings method

Use this method for any estimate of what a lifecycle change will save. It is the method the Tidewater programme reports against.

1. For each age band of the bucket (0-30d, 30-90d, 90-365d, >365d), take the band size in TB, multiply by 1000 to get GB, and multiply by the price of the storage class that the policy puts that band in.
2. Bands older than the expiry age are deleted, so they cost 0.
3. Add the bands together. That is the **monthly cost after**.
4. Ignore request, transition and retrieval fees (FinOps: <2%).
5. **Saving = current monthly cost - cost after.**
6. Round to cents.

In short: monthly cost after = sum over age bands of (band TB x 1000 x price of the class the policy puts that band in).

The storage class that "the policy puts that band in" is defined by the *Storage Tiering & Retention Policy*, including its overrides.

> **Note:** "Steady state" means the saving once the lifecycle rule has run for long enough that every object sits in its target class. It is not the saving in the first month after a change. The first month usually shows a small bump because of transition requests.

---

## 7. Bucket inventory (August 2026 snapshot)

Snapshot taken 2026-09-01. Age bands are in TB. "Avg object" and "Objects" are from Storage Lens; age bands, lifecycle rule and compliance are from the nightly inventory job; monthly cost is list-price-equivalent at the price sheet in section 5.

| Bucket | Region | Writer service | Data class | Current class | Size TB | Avg object | Objects | 0-30d | 30-90d | 90-365d | >365d | Lifecycle rule | Policy compliant | Monthly cost USD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| s3://kst-telemetry-raw-prod | us-east-1 | telematics-ingest | telemetry-raw | STANDARD | 820 | 2.4 MB | 341.7M | 60 | 110 | 380 | 270 | none | No | 18,860.00 |
| s3://kst-telemetry-raw-eu | eu-central-1 | telematics-ingest | telemetry-raw | STANDARD | 210 | 2.4 MB | 87.5M | 15 | 30 | 95 | 70 | none | No | 4,830.00 |
| s3://kst-pod-images-prod | us-east-1 | pod-service | pod-images | STANDARD | 540 | 1.1 MB | 490.9M | 25 | 40 | 175 | 300 | mobile-apps-pod-images-prod-v1 (expiry only) | No | 12,420.00 |
| s3://kst-app-logs-prod | us-east-1 | log-shipper | app-logs | STANDARD | 310 | 38 KB | 8.16B | 95 | 170 | 45 | 0 | none | No | 7,130.00 |
| s3://kst-ml-snapshots | us-east-1 | feature-store | ml-training-snapshots | STANDARD | 260 | 480 MB | 541.7K | 20 | 35 | 105 | 100 | none | No | 5,980.00 |
| s3://kst-support-attachments | us-east-1 | helpdesk-bridge | support-attachments | STANDARD | 36 | 850 KB | 42.4M | 4 | 6 | 12 | 14 | none | No | 828.00 |
| s3://kst-invoices-archive | us-east-1 | billing-core | invoices | mixed STANDARD/GLACIER_IR | 42 | 310 KB | 135.5M | 1.5 | 3 | 11.5 | 26 | billing-eng-invoices-archive-v3 | Yes | 253.50 |
| s3://kst-db-backups-prod | us-east-1 | pgbackup | db-backups | mixed STANDARD/STANDARD_IA | 190 | 5.2 GB | 36.5K | 163 | 27 | 0 | 0 | platform-core-db-backups-prod-v2 | Yes | 2,543.00 |
| s3://kst-route-cache | us-east-1 | routing-engine | ephemeral-cache | STANDARD | 14 | 12 KB | 1.17B | 14 | 0 | 0 | 0 | routing-route-cache-v4 | Yes | 322.00 |
| s3://kst-carrier-edi-inbox | us-east-1 | edi-gateway | edi-documents | STANDARD | 18 | 64 KB | 281M | 2 | 4 | 12 | 0 | integrations-carrier-edi-inbox-v1 | Yes | 414.00 |
| s3://kst-analytics-exports | us-east-1 | analytics-exporter | scratch | STANDARD | 75 | 22 MB | 3.4M | 75 | 0 | 0 | 0 | data-infra-analytics-exports-v2 | Yes | 1,725.00 |
| s3://kst-web-static | us-east-1 | web-frontend (CDN origin) | static-assets | STANDARD | 2 | 180 KB | 11.1M | 0.3 | 0.4 | 0.9 | 0.4 | exempt | Exempt | 46.00 |

**Total S3: 55,351.50 / month** (August 2026 snapshot, taken 2026-09-01).

Notes on the inventory:

- **s3://kst-pod-images-prod** has a lifecycle rule, `mobile-apps-pod-images-prod-v1`, but it is **expiry-only**: it deletes objects at the end of their retention and has no storage class transitions. Every object in the bucket is still in STANDARD, which is why the bucket shows as non-compliant even though a rule exists.
- **Mixed** in *Current class* means the bucket already has objects in more than one storage class because of an existing lifecycle rule. The monthly cost for mixed buckets is the sum of the per-class costs from Storage Lens, not size x STANDARD price.
- **Policy compliant** is `Yes` when the bucket's lifecycle rule matches the Tiering & Retention Policy for its data class, `No` when there is no rule or the rule does not match, and `Exempt` when the data class is exempt from lifecycle policy.
- The EU bucket is priced at us-east-1 list, as for every other bucket (see section 5). The real eu-central-1 bill is slightly higher; the difference goes to the *Regional uplift* line in the monthly Finance pack, not to this dashboard.

---

## 8. S3 spend trend (last six months)

Total S3 storage cost at the price sheet, by calendar month. Each figure is the monthly snapshot for that month.

| Month | Total S3 spend (USD) | Change vs previous month (USD) | Change (%) |
|---|---|---|---|
| March 2026 | 49,812.40 | +1,027.65 | +2.1% |
| April 2026 | 51,205.75 | +1,393.35 | +2.8% |
| May 2026 | 52,388.10 | +1,182.35 | +2.3% |
| June 2026 | 53,470.90 | +1,082.80 | +2.1% |
| July 2026 | 54,602.35 | +1,131.45 | +2.1% |
| August 2026 | 55,351.50 | +749.15 | +1.4% |

Commentary:

- Growth has been steady at roughly 2% a month for most of the year. Most of it is telemetry and proof-of-delivery images, which grow with shipment volume.
- April's jump came from onboarding two large regional carriers, which added telematics devices, and from a one-off backfill of historical telemetry for the ETA model.
- August growth slowed because the analytics exports scratch rule was tightened in July and because shipment volume dips in the summer.

---

## 9. Non-S3 storage costs

These costs are not part of Tidewater, but they show up on the *Storage* line of the Finance pack, so people often ask about them. August 2026, net amortised cost (not list-price-equivalent).

| Service | What it is | August 2026 (USD) | vs July |
|---|---|---|---|
| EBS volumes (gp3, io2) | Block storage attached to EC2 and EKS nodes | 14,210.40 | +1.8% |
| EBS snapshots | Point-in-time volume backups via AWS Backup | 3,882.15 | -4.6% |
| RDS snapshots | Manual and automated snapshots beyond the free allowance | 2,946.70 | +0.9% |
| EFS | Shared file systems for legacy batch jobs | 1,118.25 | -0.3% |
| CloudFront egress | Data transfer out from the CDN (customer portal, driver app assets) | 6,734.90 | +3.2% |
| **Total non-S3 storage and delivery** | | **28,892.40** | |

Notes:

- The drop in EBS snapshots is from the snapshot hygiene clean-up in July (orphaned snapshots from decommissioned EKS node groups).
- CloudFront egress is grouped here only because it appears on the storage line of the Finance pack. It is not storage.

---

## 10. Project Tidewater

**Goal:** reduce S3 spend by **45% by the end of Q4** (FY26), measured as steady-state monthly S3 cost at the price sheet, against the August 2026 snapshot baseline on this page.

**Scope:** Tidewater focuses on lifecycle remediation, meaning bringing every non-compliant bucket in line with the Tiering & Retention Policy. Exempt buckets are out of scope. The programme also has a few smaller hygiene workstreams.

**Sponsors:** VP Finance and VP Engineering. **Programme lead:** FinOps. **Technical lead:** Data Infrastructure.

### Workstream status (as of 2026-09-03)

| # | Workstream | Lead function | Status | Notes |
|---|---|---|---|---|
| WS1 | Lifecycle remediation of non-compliant buckets | Data Infrastructure with bucket owners | In progress | Buckets marked `No` in section 7. Changes go through the migration runbook. Savings to be measured with the method in section 6 once rules are applied. |
| WS2 | Incomplete multipart upload clean-up | Data Infrastructure | Done | Org-wide 7-day abort rule applied in August. Small effect on storage bytes. |
| WS3 | Storage Lens advanced metrics for all accounts | FinOps | Done | Now covers every production and staging account. |
| WS4 | Chargeback of S3 cost to teams | FinOps | In progress | Showback live since July; chargeback from October close (see section 11). |
| WS5 | Tagging coverage (`kestrel:cost-center`, `kestrel:data-class`) | FinOps | In progress | 97.8% of S3 cost tagged; target 99%. |
| WS6 | Guardrail: new buckets must have a lifecycle rule | Platform security | Proposed | SCP draft under review; would block bucket creation without a rule or an exemption tag. |

Reporting: monthly at the FinOps review, quarterly to leadership. Savings count only once a rule is live, at steady state (section 6).

---

## 11. Cost allocation tags and chargeback

### Required tags

Every S3 bucket in a production account must have the following tags. The nightly inventory job flags missing tags, and they show up on the *Untagged spend* tile.

| Tag key | Example value | Purpose |
|---|---|---|
| `kestrel:cost-center` | `CC-4120` | Chargeback. Must be a valid code from the table below. |
| `kestrel:data-class` | `telemetry-raw` | Drives policy compliance reporting. |
| `kestrel:environment` | `prod` | Separates production from staging and sandbox spend. |

Tags are activated as cost allocation tags in the payer account. A newly created tag key takes up to 24 hours to show up in the CUR, and it does not apply retroactively.

### Cost center codes

| Cost center | Description |
|---|---|
| CC-4100 | Engineering - shared platform and infrastructure |
| CC-4120 | Engineering - data and analytics |
| CC-4140 | Engineering - product (customer portal, driver app) |
| CC-4160 | Engineering - integrations and carrier connectivity |
| CC-4180 | Engineering - routing and forecasting |
| CC-5200 | Finance - billing operations |
| CC-6300 | Customer Operations - support |
| CC-9999 | Unallocated (should be empty; anything here is a tagging bug) |

Which bucket belongs to which team is recorded on *Storage Architecture & Service Ownership*, not here. The cost center tag must match the owning team's cost center; the nightly job reports mismatches to FinOps.

### Chargeback process

- **Showback** (live since July 2026): each team lead gets a monthly email on the 7th with their S3 and non-S3 storage cost, taken from the snapshot.
- **Chargeback** (from October 2026 close): storage cost is journaled from CC-4100 to the owning cost center on working day 5. Disputes must be raised with FinOps by working day 8; after that the journal is final.
- Tidewater savings are credited to the cost center of the bucket, so teams that remediate their buckets see the benefit in their own budget line.

---

## 12. FAQ

**Why does the dashboard not match the AWS bill?**
The dashboard uses list-price-equivalent cost at a fixed price sheet (section 5), and normalises eu-central-1 to us-east-1. The bill includes our EDP discount, credits and real regional prices. For trends and savings, the dashboard is the right number. For the actual spend, use the Finance pack.

**Why is a bucket with a lifecycle rule still "non-compliant"?**
A rule exists, but it does not match the policy for the data class. The usual case is an expiry-only rule, like the one on s3://kst-pod-images-prod: it deletes old objects but never moves anything out of STANDARD.

**Where do I find out which storage class a band should be in?**
In *Storage Tiering & Retention Policy*. That page has the schedule and the overrides. This page only has prices and the arithmetic.

**Do I need to include retrieval fees in a savings estimate?**
No. The steady-state method ignores request, transition and retrieval fees because FinOps has measured them at under 2% of S3 cost. If you think your bucket is an exception (for example, heavy re-reads of old data), raise it at the FinOps review.

**Can I round intermediate numbers?**
No. Keep full precision through the calculation and round only the final figures to cents.

---

## 13. Notes from the FinOps review, 2026-09-03

**Attendees:** FinOps (chair), Data Infrastructure, Platform, Finance business partner for Engineering, representatives from the Mobile, Billing and Integrations teams.
**Apologies:** Forecasting (covered asynchronously).

### Discussion

1. **August snapshot.** Total S3 of 55,351.50 USD at the price sheet, up 1.4% on July. Snapshot confirmed; no CUR restatement expected. The group agreed to use the August snapshot as the Tidewater baseline.
2. **Compliance.** Six buckets are non-compliant, and they are most of the S3 spend. Five have no lifecycle rule. One (proof-of-delivery images) has an expiry-only rule. The group agreed WS1 should work through all six this quarter and not wait for WS6.
3. **Savings method.** Should first-month transition fees be netted off? Decision: no; steady-state method as before.
4. **EU pricing.** Should the EU telemetry bucket use eu-central-1 rates? Decision: no; keep normalising to us-east-1.
5. **Chargeback.** October go-live confirmed. FinOps will send a September shadow month.
6. **Tagging.** 2.2% of S3 cost is still untagged, mostly from sandbox accounts. Platform will chase.

### Action items

| # | Action | Owner | Due | Status |
|---|---|---|---|---|
| A1 | Publish August snapshot on this page and lock it as Tidewater baseline | FinOps | 2026-09-05 | Done |
| A2 | Raise change tickets for each non-compliant bucket in section 7 | Data Infrastructure | 2026-09-17 | In progress |
| A3 | Confirm each bucket owner's storage approver is current on the ownership page | Data Infrastructure | 2026-09-10 | Done |
| A4 | Send September shadow chargeback emails | FinOps | 2026-10-07 | Open |
| A5 | Fix untagged sandbox buckets | Platform | 2026-09-30 | In progress |
| A6 | Draft SCP for WS6 guardrail and circulate for comment | Platform security | 2026-09-24 | Open |
| A7 | Open CloudFront egress investigation (separate from Tidewater) | FinOps | 2026-09-17 | Open |

Next review: 2026-10-08.

---

## 14. Revision history

| Date | Version | Author | Change |
|---|---|---|---|
| 2026-09-05 | 3.4 | FinOps | Published August 2026 snapshot (taken 2026-09-01). Marked as Tidewater baseline. Added notes from 2026-09-03 review. |
| 2026-08-06 | 3.3 | FinOps | Published July 2026 snapshot. Added non-S3 storage table. |
| 2026-06-04 | 3.1 | FinOps | Published May 2026 snapshot. Moved the tier and schedule tables to *Storage Tiering & Retention Policy* so there is only one copy. |
| 2026-05-06 | 3.0 | FinOps, Data Infrastructure | Page restructured for Project Tidewater. Added steady-state savings method and fixed price sheet with EU normalisation. |
