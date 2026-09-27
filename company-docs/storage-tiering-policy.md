# Storage Tiering & Retention Policy

| Field | Value |
|---|---|
| **Doc id** | `storage-tiering-policy` |
| **Space** | Perch > Engineering > Data Infrastructure > Policies |
| **Policy version** | v3.2 |
| **Owner** | Data Infrastructure |
| **Approved by** | Storage Council |
| **Last reviewed** | 2026-08-14 |
| **Next scheduled review** | 2026-11 (Q4 Storage Council) |
| **Status** | Active |

> **ℹ️ Info**
> This page is the single source of truth for **which storage tier data lives in, and for how long**. If another Perch page, a Slack thread, a README, or a Terraform comment disagrees with this page, this page wins. Please raise a comment below (or ping the Storage Council channel) rather than editing numbers yourself. Edits to the tables on this page require Storage Council approval and a new revision entry.

> **📎 Related pages**
> - **Storage Cost Dashboard & Bucket Inventory** - current bucket sizes, age bands, pricing and compliance status.
> - **Runbook: Lifecycle Migrations with blobctl** - how to actually implement the rules on this page.
> - **Storage Architecture & Service Ownership** - which team owns which bucket, and the service tier of every service.

---

## 1. Purpose & scope

Kestrel Logistics stores a large and growing volume of operational data in Amazon S3, from vehicle telemetry and proof-of-delivery (POD) photos to invoices, backups and scratch space. Left alone, all of it sits in S3 STANDARD forever, which is expensive and, for some data, a compliance problem (we must delete certain data after a fixed period, and *keep* other data for a fixed period).

This policy defines:

- the four **Kestrel storage tiers** and the S3 storage class that backs each one;
- the **data class schedule**, i.e. for each registered data class, which tier an object belongs in at a given age and when it must be deleted;
- the **overrides** that modify the schedule for particular buckets;
- the surrounding requirements for encryption, replication, legal hold, privacy deletion and exceptions.

**In scope:** every S3 bucket in every Kestrel-owned AWS account, in both `us-east-1` (primary) and `eu-central-1` (EU), including buckets created by vendors on our behalf.

**Out of scope:** EBS volumes and snapshots, RDS automated snapshots, endpoint storage, and SaaS tools that store data outside our AWS accounts.

This policy tells you *what* the lifecycle of a bucket must be. It deliberately does not tell you *how* to implement it; for that, see **Runbook: Lifecycle Migrations with blobctl**. It also does not list bucket sizes or costs; those are on **Storage Cost Dashboard & Bucket Inventory**.

---

## 2. Background & policy history

### v1 (2023) - "Keep everything"

The original Storage Retention Policy was written in early 2023, shortly after Kestrel moved its last on-prem file servers in Columbus into AWS. It mostly said "retain everything for seven years unless Legal says otherwise." There was no tiering; every bucket was S3 STANDARD, and nothing was enforced by tooling.

### v2 (2024) - Tiers introduced

In 2024, after S3 became the third-largest line on the AWS bill, Data Infrastructure introduced the Hot / Warm / Cold / Frozen tier vocabulary and the first version of the data class schedule. v2 was aggressive: almost every data class moved to Frozen (S3 Glacier Deep Archive) after 180 days. It also introduced the Storage Council (see section 7) as the approving body for schedule changes.

### v3 (2025) - After the Deep Archive retrieval incident

In mid-2025 a customer-facing, synchronous dispute workflow needed to read historical objects that v2 had moved into Deep Archive. Deep Archive retrieval takes 12-48 hours; the workflow's SLO is measured in seconds. The result was a multi-day incident, breached customer SLAs, and post-incident review PIR-2025-031.

The two lessons that shaped v3:

1. **Frozen is not "cheap Cold".** Deep Archive is an archive, not a storage tier you can serve reads from. Anything that a latency-sensitive production service may read must never be Frozen.
2. **Tiny objects do not benefit from tiering.** The same review found that several buckets full of small objects were costing *more* after v2 transitions because of minimum billable object sizes and per-object overhead.

v3 therefore introduced the **Overrides** section (section 6), capped Frozen for several data classes, and added the requirement that every bucket's owner and service readers be recorded on **Storage Architecture & Service Ownership**. v3.1 and v3.2 are clarifications; see section 14.

> **⚠️ Note**
> If you are reading an old design doc that references "the 180-day Frozen rule," that is v2 and is no longer valid.

---

## 3. Definitions

| Term | Meaning |
|---|---|
| **Tier** | One of the four Kestrel storage tiers (Hot, Warm, Cold, Frozen). Always capitalised on this page. |
| **Storage class** | The AWS S3 storage class that backs a tier, e.g. `STANDARD_IA`. Tooling and lifecycle rules use storage class names, not tier names. |
| **Data class** | A registered category of data with a single retention schedule, e.g. `telemetry-raw`. Every bucket has exactly one data class. |
| **Schedule** | The row of the data class table that says which tier an object belongs in at each age, and when it expires. |
| **Age** | Days since object creation (the S3 object creation date), not days since last access or last modification of the bucket. |
| **Expire / Expiry** | Permanent deletion of the object (and, for versioned buckets, its non-current versions) once it reaches the stated age. |
| **Override** | A rule in section 6 that restricts the schedule for a specific bucket, regardless of its data class. |
| **Tier-1 service** | A service classified as Tier-1 on **Storage Architecture & Service Ownership**: customer-facing or revenue-critical, with a synchronous read path and a paging on-call. |
| **Policy compliant** | A bucket whose lifecycle rule matches this policy, including overrides. Compliance status is reported on the cost dashboard. |

---

## 4. Storage tiers

Kestrel uses four tiers. Each tier maps to exactly one S3 storage class. Do not use any other S3 storage class (e.g. `ONEZONE_IA`, `INTELLIGENT_TIERING`, `GLACIER` Flexible Retrieval) without an approved exception.

| Kestrel tier | Storage class | Retrieval | Min storage duration | Min billable object size |
|---|---|---|---|---|
| Hot | STANDARD | ms | none | none |
| Warm | STANDARD_IA | ms | 30 days | 128 KB |
| Cold | GLACIER_IR | ms | 90 days | 128 KB |
| Frozen | DEEP_ARCHIVE | 12-48 h | 180 days | 40 KB overhead |

Notes on the tiers:

- **Hot, Warm and Cold all serve reads in milliseconds.** They differ in storage cost versus per-request and retrieval charges.
- **Frozen does not serve reads.** An object in Frozen must be restored first, which takes 12-48 hours. Treat Frozen as "we are keeping this for the record."
- **Minimum storage duration** means an object deleted or transitioned out before that many days is billed as if it had stayed the full duration. This is why the schedule never puts data into a tier shortly before it expires.
- **Minimum billable object size** means objects smaller than 128 KB in Warm or Cold are billed as 128 KB. Frozen adds roughly 40 KB of per-object overhead. For small objects this can wipe out any saving; see the small-objects override.

---

## 5. Data class schedule

Ages are **days since object creation**. A range such as `30-90` means the object is in that tier from day 30 until day 90. `>365` means from day 365 onwards. `-` means the tier is skipped. `all` means the object stays in that tier for its entire life. The Expire column is the age at which the object is deleted.

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

How to read the table:

- The schedule is the **default** for the data class. The overrides in section 6 can remove tiers from it for a particular bucket; they never add tiers.
- **"not permitted"** in the Frozen column is a hard cap for that data class (see "Data-class caps" in section 6).
- **invoices** have no automatic expiry. Deletion after the statutory retention period is a manual process owned by Legal.
- **static-assets** (CDN origin content, web bundles, email templates) are exempt from lifecycle policy entirely. Do not add lifecycle rules to exempt buckets.

> **💡 Tip**
> If your data does not fit any of these classes, do not pick the "closest" one. Register a new data class (section 7). Mis-classified buckets are the single most common audit finding.

---

## 6. Overrides

The schedule in section 5 describes the ideal lifecycle for a data class. The overrides below restrict it for specific buckets. **Apply every override that matches.** When overrides and the schedule disagree, the more restrictive result wins (fewer tiers, shallower deepest tier). Overrides only ever remove transitions; they never change the Expire value.

### 6.1 Small objects (<128 KB)

If a bucket's **average object size is below 128 KB**, it gets **no Warm, Cold or Frozen transitions**. Objects stay **Hot until they expire**.

Rationale: Warm and Cold have a 128 KB minimum billable object size and Frozen adds per-object overhead, so transitioning small objects typically costs more than leaving them in STANDARD. The average object size for each bucket is published on **Storage Cost Dashboard & Bucket Inventory**. Expiry still applies as per the schedule.

### 6.2 Tier-1 readers - no Frozen

If **any Tier-1 service reads a bucket**, **Frozen is not permitted** for that bucket; **the deepest tier is Cold**. This applies even if the Tier-1 service reads the bucket rarely, and even if the Tier-1 service is not the bucket's writer or owner.

Service tiers, and which services read which buckets, are listed on the **Storage Architecture & Service Ownership** page. This policy intentionally does not duplicate that list; always check the ownership page for the current service tiers before deciding whether a bucket may go to Frozen.

Rationale: this is the direct lesson of the 2025 Deep Archive retrieval incident (section 2). Cold (`GLACIER_IR`) still serves reads in milliseconds, so capping at Cold preserves the Tier-1 read path.

### 6.3 Statutory retention (invoices)

**Invoices must never go to Frozen within the 7-year retention period.** Invoice data is subject to statutory retention and must remain retrievable in milliseconds for audit and tax enquiries throughout that period. Invoices also have no automatic expiry; deletion after the retention period is a manual, Legal-owned process.

### 6.4 Data-class caps

**Where the schedule says "not permitted" for Frozen, that is a cap.** The data class's deepest tier is the last tier before Frozen in its row, regardless of bucket-level considerations. Data-class caps are set by the Storage Council when a data class is registered or reviewed and can only be lifted by a schedule change, not by an exception.

> **⚠️ Warning**
> Overrides are evaluated **per bucket**, not per data class. Two buckets with the same data class can legitimately end up with different lifecycle rules (for example, if a Tier-1 service reads one but not the other). Always check the current reader list and average object size for the specific bucket.

---

## 7. Data classification process

### 7.1 Registering a new data class

Every new bucket must be assigned one of the registered data classes above **before** it receives production writes. If none fit:

1. Open a "New data class" request using the template in the Data Infrastructure intake queue.
2. Describe the data, its writers and readers, expected volume and object size, any retention obligation, and whether it contains personal data.
3. Propose a schedule (Hot / Warm / Cold / Frozen / Expire) and justify each step.
4. Legal and Security review the request asynchronously (target: 10 business days).
5. The Storage Council approves, amends or rejects the request at its next meeting.
6. On approval, Data Infrastructure adds the class to section 5 and bumps the policy minor version.

### 7.2 The Storage Council

The Storage Council is a standing cross-functional group that owns this policy. Membership:

- Data Infrastructure (chair, policy owner)
- Platform Engineering
- Security (GRC)
- Legal (privacy & records)
- FinOps (Finance)
- One rotating representative from a product engineering team

The Council meets **monthly** for requests and **quarterly** for a full review of the schedule. Quorum is four members including the chair and Legal. Minutes are posted to the Storage Council page. @helen.voss takes minutes; ping her to add an agenda item.

### 7.3 Quarterly review

Each quarter the Council:

- reviews every data class schedule against actual access patterns (S3 Storage Lens and server access logs);
- reviews open exceptions and their expiry dates;
- records the outcome as a revision entry in section 14, even if nothing changed.

---

## 8. Encryption & KMS requirements

All data in scope of this policy must be encrypted at rest and in transit, regardless of tier.

- **At rest:** SSE-KMS with a customer-managed KMS key is mandatory for any bucket holding personal data, financial data or customer documents. SSE-S3 is acceptable only for `ephemeral-cache`, `scratch` and `static-assets` data classes.
- **Key rotation:** automatic annual rotation must be enabled on every CMK.
- **In transit:** bucket policies must deny any request where `aws:SecureTransport` is false.
- **Tiering does not change encryption.** Objects keep their encryption when they transition between storage classes. Do not re-encrypt objects as part of a lifecycle change.

---

## 9. Cross-region replication

Kestrel's primary region is `us-east-1`; `eu-central-1` hosts data for EU customers and carriers.

- **Data residency first.** EU personal data written in `eu-central-1` must not be replicated to `us-east-1` or any other non-EU region. This overrides any DR preference.
- **Replication is opt-in.** Cross-region replication (CRR) is enabled only where there is a documented DR requirement, currently limited to `invoices` and `db-backups` data classes in the US.
- **Replicas follow the same schedule.** A replica bucket has the same data class as its source and must have an equivalent lifecycle rule, including overrides. A replica is not an excuse to skip expiry.
- **Delete marker replication** must be enabled so that expiry and privacy deletions propagate to replicas.

---

## 10. Legal hold

A legal hold suspends expiry for identified data because of litigation, regulatory investigation or a credible threat of either.

1. **Issuing a hold.** Only Legal can issue a hold, via a Legal Hold Notice identifying the data by bucket, prefix, data class and/or date range.
2. **Implementing a hold.** Data Infrastructure applies S3 Object Lock legal hold (or, where Object Lock is not enabled on the bucket, suspends the expiry action on the affected prefix) within **two business days** of the notice.
3. **Tiering under hold.** A hold suspends *expiry* only. Transitions continue as normal, **except** that held data must not be moved to Frozen if Legal indicates it may need to be produced quickly. Legal will say so in the notice.
4. **Releasing a hold.** Only Legal can release a hold. On release, normal expiry resumes; objects already past their Expire age are deleted at the next lifecycle run.

> **⚠️ Warning**
> Never remove a legal hold or an Object Lock configuration to "fix" a lifecycle rule. If a hold is blocking a change, contact Legal (@anika.feld, Records Counsel) directly.

---

## 11. Privacy deletion requests (GDPR / CCPA)

Kestrel receives data subject requests (DSRs) from drivers, consignees and customer staff under GDPR, CCPA/CPRA and similar laws.

- **Deadline.** Deletion must be completed within the statutory period (typically 30 days for GDPR, 45 days for CCPA). Privacy tracks the clock.
- **Tier does not matter.** Personal data must be deleted wherever it lives, including Warm, Cold and Frozen. Frozen objects can be deleted without restoring them first; do not restore Frozen data just to delete it.
- **Statutory retention wins.** Where data is under statutory retention (for example invoices) or legal hold, Privacy will inform the requester that the data is retained under a legal obligation. The data is not deleted early.
- **Backups.** Personal data in `db-backups` is not individually deleted; it ages out through the 35-day expiry. Privacy discloses this in its response.

---

## 12. Exceptions

Occasionally a bucket needs to deviate from this policy for a reason the overrides do not cover (e.g. a vendor contract requiring longer retention).

1. The bucket's owning team raises an exception request in the Storage Council queue, stating the bucket, the deviation, the reason, the risk, and a proposed end date.
2. Exceptions are **time-boxed**: maximum 12 months, renewable once.
3. Security and Legal review for compliance impact; FinOps reviews for cost impact.
4. The Storage Council approves or rejects at its next monthly meeting. Urgent requests can be approved out of cycle by the chair plus Legal.
5. Approved exceptions are recorded in the exceptions register on the Storage Council page and reviewed quarterly.

What an exception **cannot** do:

- lift a data-class cap (that requires a schedule change);
- allow Frozen for a bucket read by a Tier-1 service;
- shorten statutory retention;
- override a legal hold.

Note that the overrides in section 6 are part of the policy itself; a bucket that is not tiered all the way to Frozen because of an override does **not** need an exception. How that reason is recorded during a migration is covered in **Runbook: Lifecycle Migrations with blobctl**.

---

## 13. FAQ

**Q: Is "age" based on when the object was last read?**
No. Age is always days since object creation. S3 lifecycle rules do not know about reads, and we do not use Intelligent-Tiering.

**Q: My bucket's data class allows Frozen, but a Tier-1 service reads it. Which wins?**
The override wins. Frozen is not permitted and the deepest tier is Cold. Check **Storage Architecture & Service Ownership** for current service tiers and readers; a bucket's readers can change over time.

**Q: Our objects average 90 KB. Should we move them to Warm anyway to save something?**
No. Below 128 KB average object size, the bucket stays Hot until expiry. Warm would bill each object as 128 KB and very likely cost more.

**Q: Can we put invoices in Frozen after, say, five years to save money?**
No. Invoices must never go to Frozen within the 7-year statutory retention period, and the data class caps Frozen as "not permitted" in any case. Deletion after retention is manual and owned by Legal.

**Q: Why does `app-logs` skip Cold?**
The logs expire at 90 days. Cold has a 90-day minimum storage duration, so transitioning into Cold shortly before expiry would cost more, not less.

**Q: How do I actually change a bucket's lifecycle rule?**
Follow **Runbook: Lifecycle Migrations with blobctl**. Do not edit lifecycle configurations in the AWS console; console changes are overwritten and flagged as drift.

**Q: Our static site bucket has no lifecycle rule. Is it non-compliant?**
No. `static-assets` is exempt from lifecycle policy. Exempt buckets should not be given lifecycle rules.

---

## 14. Revision history

| Version | Date | Author | Summary |
|---|---|---|---|
| v1.0 | 2023-03-02 | Data Infrastructure | Initial Storage Retention Policy. Seven-year default retention; no tiering. |
| v1.1 | 2023-09-18 | Data Infrastructure | Added encryption requirements for SOC 2 Type II. |
| v2.0 | 2024-04-09 | Data Infrastructure | Introduced Hot / Warm / Cold / Frozen tiers and the data class schedule. Formed the Storage Council. |
| v2.1 | 2024-10-22 | Data Infrastructure | Added `edi-documents` and `ephemeral-cache` data classes. |
| v3.0 | 2025-08-05 | Data Infrastructure | Post-incident rewrite after PIR-2025-031. Added Overrides section (small objects, Tier-1 readers, statutory retention, data-class caps). Frozen capped for `pod-images`, `support-attachments`, `invoices`. |
| v3.1 | 2026-02-11 | Data Infrastructure | Added `scratch` data class; clarified that age is days since object creation; clarified GDPR/CCPA handling of Frozen objects. |
| v3.2 | 2026-08-14 | Data Infrastructure | Q3 Storage Council review. Clarified that overrides are evaluated per bucket and that service tiers live only on the ownership page; tightened cross-region replication wording. No schedule changes. |

> **✅ Approved**
> v3.2 approved by the Storage Council on 2026-08-14. Minutes are on the Storage Council page.
