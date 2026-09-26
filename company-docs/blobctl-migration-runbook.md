# Runbook: Lifecycle Migrations with blobctl

| | |
|---|---|
| **Doc ID** | `blobctl-migration-runbook` |
| **Space** | Perch > Engineering > Data Infrastructure > Storage |
| **Owner** | Data Infrastructure / Storage on-call (`data-infra-primary`) |
| **Programme** | Project Tidewater (FY26 storage cost reduction) |
| **Applies to** | blobctl 1.9 |
| **Last updated** | 2026-07-30 |
| **Status** | Current |

> **Info:** This page is the operational "how". The "what" lives on three companion pages, and you will need all three open while you work:
> - **Storage Tiering & Retention Policy**: tiers, data class schedules, overrides.
> - **Storage Cost Dashboard & Bucket Inventory**: which buckets are in scope, current lifecycle rules, sizes and cost.
> - **Storage Architecture & Service Ownership**: bucket owners, team handles, storage approvers, service tiers.
>
> This runbook deliberately does not repeat their contents. If a number, handle or schedule is not on this page, look it up on the page that owns it. Do not copy values from old change tickets; they go stale.

---

## 1. When to use this runbook

Use this runbook whenever you are creating, replacing or removing an S3 lifecycle rule on a Kestrel-managed bucket. In practice that means:

- Tidewater migrations: moving a non-compliant bucket onto the schedule its data class requires.
- Re-tiering after a data class change (for example, a bucket reclassified by its owning team).
- Adding or changing expiry after a retention decision from Legal or the owning team.
- Replacing a hand-written or console-created lifecycle rule with a blobctl-managed one.

Do **not** use this runbook for:

- Bucket creation, deletion or replication changes. See "Provisioning S3 Buckets with Terraform".
- Object-level restores from archive tiers. See "Restoring Archived Objects" (and read section 12 of this page first).
- Legal holds or Object Lock. These are owned by Legal and Security; open a ticket in the `LEGALOPS` queue.
- Buckets marked **Exempt** on the cost dashboard. Exempt buckets are never touched by lifecycle work, full stop, even if they look expensive.

## 2. How lifecycle changes flow

blobctl is the storage control plane tool (repo `kestrel/blobctl`). For this runbook we assume blobctl 1.9, which is installed on the ops bastion and in agent workspaces at `bin/blobctl`.

All lifecycle changes land in the **staging control plane first**. Nothing you run in this runbook writes directly to production. Once a staged rule is applied and approved, the **weekly promotion job** (Wednesdays 14:00 ET, run by Storage on-call) promotes approved staging rules to production.

> **Warning:** Agents and service accounts never touch production directly. If you find yourself looking for a way to "skip staging" or "push straight to prod", stop. That path does not exist for a reason, and asking for it in #storage-changes will get you a polite no. Urgent changes go through the break-glass process in section 13.

The lifecycle of a single change looks like this:

1. **Plan** (`blobctl plan`): a dry run that validates the rule and records a plan against a rule id.
2. **Apply** (`blobctl apply`): applies the recorded plan to staging, tied to a change ticket and a named approver.
3. **Status** (`blobctl status`): confirms the plan and applied rule, after which you update the change ticket.
4. **Promotion**: the Wednesday job promotes approved staged rules to production. You do not run this.
5. **Verification**: post-promotion checks (section 10).

## 3. Scope: which buckets are in play

For Project Tidewater, the scope rule is simple and it is the only rule:

- A bucket is **in scope** if its **"Policy compliant"** value on the Storage Cost Dashboard & Bucket Inventory is **"No"**.
- Buckets showing **"Yes"** are already compliant. Leave them alone unless their owning team asks for a change through the normal process.
- Buckets showing **"Exempt"** are **never touched**.

> **Note:** "In scope" is decided by the dashboard, not by how big or expensive a bucket looks, and not by a Slack thread. If you think a compliant bucket is wrong, raise it with FinOps in #tidewater rather than migrating it.

## 4. Pre-flight checklist

Work through this before you run `blobctl plan`. Most failed migrations in FY25 skipped at least one of these.

- [ ] Bucket is in scope per section 3 (dashboard shows "Policy compliant" = No).
- [ ] You have the bucket's **data class** and **current lifecycle rule** from the cost dashboard.
- [ ] You have looked up the bucket's **owning team**, that team's **handle** and its **storage approver** on the Storage Architecture & Service Ownership page.
- [ ] You have checked **which services read the bucket** and their service tiers on the same page.
- [ ] You have checked the bucket's **average object size** on the dashboard.
- [ ] You have worked out the target schedule from the Storage Tiering & Retention Policy, **after applying every override** in its "Overrides" section.
- [ ] A change ticket (`CHG-` number) exists in the `STORCHG` queue with the bucket, the target schedule and the planned exception code.
- [ ] The current date is not inside a change freeze (section 8).
- [ ] You have posted, or are ready to post, the #storage-changes announcement (section 9).

> **Tip:** Write the target schedule into the change ticket *before* you touch blobctl.

## 5. Building the rule

### 5.1 Transition syntax

Transitions are expressed as:

```
--transition <days>:<STORAGE_CLASS>
```

Rules for transitions:

- `<days>` is **days since object creation**.
- Transitions are listed in **ascending** order of days.
- `<STORAGE_CLASS>` is the **S3 storage class name** (for example `STANDARD_IA`), **not** the Kestrel tier name. blobctl rejects `Warm`, `Cold` and friends. The mapping from tiers to storage classes is on the Storage Tiering & Retention Policy page.
- Objects start in `STANDARD`, so **never add a transition to `STANDARD`**.
- **Only include tiers the bucket actually uses after overrides.** If an override removes a tier, the transition for that tier is simply left out.

Expiry is expressed as:

```
--expire <days>
```

`--expire` sets expiry in days since object creation. **Omit it only if the data class has no expiry.** If you are unsure whether expiry applies, the answer is in the data class schedule on the policy page, not in the current rule.

### 5.2 Rule id convention

Every blobctl-managed rule has an id of the form:

```
<owning-team-handle>-<bucket name without the "kst-" prefix>-v<N>
```

- `<owning-team-handle>` is the handle of the team that owns the bucket, taken from the Storage Architecture & Service Ownership page. It is the owning team's handle, not the handle of the team that happens to write to or read from the bucket.
- The bucket name segment drops the leading `kst-`.
- `N` is the version number in the bucket's **current lifecycle rule** on the cost dashboard **plus 1**, or **1** if the bucket has no rule.
- The new rule **replaces** the old one. You do not delete the old rule separately.

Worked example: a bucket `s3://kst-dispatch-audit-2024` owned by a team with handle `fleet-ops`, whose current rule is `fleet-ops-dispatch-audit-2024-v1`, gets new rule id `fleet-ops-dispatch-audit-2024-v2`.

> **Note:** A rule that only sets expiry (the dashboard sometimes shows these as "expiry only") still counts as a current rule. Bump its version; do not start again at v1.

### 5.3 Exception codes

Every change ticket for a Tidewater migration records one **exception code**. It explains why a bucket is **not tiered all the way to Frozen**. Valid codes:

| Code | Meaning (short) |
|---|---|
| `NONE` | Bucket is tiered all the way to Frozen. No exception. |
| `STATUTORY_RETENTION` | Statutory retention rules prevent Frozen. |
| `TIER1_READER` | A Tier-1 service reads the bucket, so Frozen is not permitted. |
| `DATA_CLASS_CAP` | The data class schedule caps the bucket below Frozen. |
| `SMALL_OBJECTS` | Average object size is too small for archive tiers. |

If more than one applies, record **the first** in this precedence order:

1. `STATUTORY_RETENTION`
2. `TIER1_READER`
3. `DATA_CLASS_CAP`
4. `SMALL_OBJECTS`

> **Warning:** Record one code, not a list. The FinOps report parses this field and a comma-separated value breaks the quarterly rollup. If you believe two apply, note the second one in the ticket description in prose.

The details of each override (thresholds, what counts as a Tier-1 reader, which data classes are capped) are in the "Overrides" section of the Storage Tiering & Retention Policy.

## 6. Running the migration

### Step 1: Plan

`blobctl plan` is a dry run. It validates the rule, prints the resulting schedule and **records a plan** against the rule id. Nothing is applied.

The canonical example:

```
blobctl plan --bucket s3://kst-telemetry-raw-eu --rule-id data-infra-telemetry-raw-eu-v1 --transition 30:STANDARD_IA --transition 90:GLACIER_IR --transition 365:DEEP_ARCHIVE --expire 1095
```

Always pass `--bucket` as the **full `s3://` URI**. Read the plan output carefully: it echoes the bucket, rule id, each transition and the expiry. If any of those is not what you wrote in the change ticket, fix the command and plan again. Re-planning the same rule id overwrites the earlier plan.

### Step 2: Apply

Apply only after a plan exists for the **same rule id**:

```
blobctl apply --rule-id <rule-id> --change <CHG-number> --approver <@handle of the owning team's storage approver>
```

- `--rule-id` must match the planned rule id exactly.
- `--change` is the `CHG-` number of the change ticket.
- `--approver` is the `@handle` of the **owning team's storage approver**, as listed on the Storage Architecture & Service Ownership page. Not your manager, not the Tidewater lead, not whoever reviewed your ticket.

`apply` fails if no plan exists for the rule id. That is intentional; do not work around it.

### Step 3: Status and ticket update

```
blobctl status
```

`blobctl status` shows recorded plans and applied rules. Confirm your rule appears as applied with the right change number and approver, then **update the change ticket** with:

- the final rule id,
- the exception code (section 5.3),
- a paste of the relevant `blobctl status` lines,
- the promotion Wednesday you expect it to go out on.

Example status output (abridged):

```
RULE ID                               BUCKET                             STATE     CHANGE      APPROVER
fleet-ops-dispatch-audit-2024-v2      s3://kst-dispatch-audit-2024       applied   CHG-20417   @ines.kowalczyk
yard-systems-yard-cam-archive-v1      s3://kst-yard-cam-archive          planned   -           -
```

A rule in `planned` state has a recorded plan but has not been applied. A rule in `applied` state is staged and waiting for the Wednesday promotion job.

## 7. Worked examples (historical)

These are real migrations from the FY25 clean-up, lightly edited. The buckets involved are not part of Tidewater's current scope, and some of the teams have since been reorganised, so **do not reuse the handles or approvers below**. Always look up the current owner and approver on the ownership page.

### 7.1 Full tiering, no exception: `s3://kst-dispatch-audit-2024`

Dispatch audit trails, owned at the time by Fleet Ops (`fleet-ops`). The bucket had an expiry-only rule at v1. No overrides applied, so it went all the way to Frozen.

```
blobctl plan --bucket s3://kst-dispatch-audit-2024 --rule-id fleet-ops-dispatch-audit-2024-v2 --transition 30:STANDARD_IA --transition 90:GLACIER_IR --transition 365:DEEP_ARCHIVE --expire 2190
blobctl apply --rule-id fleet-ops-dispatch-audit-2024-v2 --change CHG-20417 --approver @ines.kowalczyk
blobctl status
```

Exception code recorded: `NONE`.

### 7.2 Tier-1 reader caps the bucket at Cold: `s3://kst-yard-cam-archive`

Yard camera stills, owned by Yard Systems (`yard-systems`), with no existing rule. A Tier-1 gate-check service read the bucket synchronously, so Frozen was not permitted and the deepest tier was Cold. Note that there is simply no Frozen transition; nothing else changes.

```
blobctl plan --bucket s3://kst-yard-cam-archive --rule-id yard-systems-yard-cam-archive-v1 --transition 30:STANDARD_IA --transition 180:GLACIER_IR --expire 730
blobctl apply --rule-id yard-systems-yard-cam-archive-v1 --change CHG-20533 --approver @rafael.osei
```

Exception code recorded: `TIER1_READER`.

### 7.3 Small objects, expiry only: `s3://kst-geofence-events`

Geofence enter/exit events, owned by Fleet Ops, average object size about 9 KB, current rule at v2. Because the small-objects override applied, the bucket got **no** transitions at all; objects stay in `STANDARD` until they expire.

```
blobctl plan --bucket s3://kst-geofence-events --rule-id fleet-ops-geofence-events-v3 --expire 180
blobctl apply --rule-id fleet-ops-geofence-events-v3 --change CHG-20610 --approver @ines.kowalczyk
```

Exception code recorded: `SMALL_OBJECTS`.

> **Tip:** In 7.3 the first draft of the plan included `--transition 30:STANDARD_IA`. Reviewers caught it: for tiny objects the minimum billable size means "cheaper" tiers can cost more than `STANDARD`. When an override removes tiers, trust the override.

## 8. Change windows and freeze calendar

Lifecycle changes are low-risk individually, but a bad transition on a large bucket can generate millions of transition requests and a surprising bill. We therefore respect the following windows.

**Standard window.** Plans and applies can be run any business day. Promotion only happens at the Wednesday 14:00 ET job, so anything applied and approved by Wednesday 12:00 ET is normally picked up that week. Later than that and it may slip a week.

**Freezes.**

| Freeze | When | Scope |
|---|---|---|
| Month-end close | Last 3 business days of the month through the 2nd business day of the next month | All buckets owned by or read by **Billing**. Finance close depends on invoice retrieval. |
| Peak season | Monday before US Thanksgiving through January 5 | All production storage changes, except break-glass. |
| Company holidays | Kestrel observed holidays | No promotion job runs; the next Wednesday picks up. |

> **Warning:** The month-end close freeze applies to anything Billing owns *or reads*, and it applies to staging applies as well as promotion. Do not plan Billing work in the last week of the month.

The authoritative freeze calendar is the "Change Freeze Calendar" page in the SRE space. If this table and that page disagree, that page wins.

## 9. Comms templates

Post in **#storage-changes** when you apply, and again after promotion. Keep it short.

**Apply announcement:**

```
:package: Lifecycle change staged
Bucket: s3://<bucket>
Rule: <rule-id> (replaces <old-rule-id or "none">)
Change: <CHG-number> | Approver: <@approver>
Schedule: <e.g. IA @30d, GIR @90d, expire 1095d>
Exception: <code>
Expected promotion: Wed <date> 14:00 ET
Owning team: <team>, cc <on-call rotation>
```

**Post-promotion confirmation:**

```
:white_check_mark: Promoted: <rule-id> on s3://<bucket> (<CHG-number>)
First transitions expected within 24-48h. Verification in thread.
```

For buckets read by customer-facing services, also give a heads-up in the owning team's channel at least one business day before the promotion Wednesday.

## 10. Verification

Transitions are applied by S3 asynchronously, usually starting within 24-48 hours of promotion and completing over several days for large buckets. Verify in three passes.

**Day 1 (after promotion):**
- `blobctl status` shows the rule as promoted.
- In the S3 console, the bucket's Management tab lists exactly one lifecycle rule, with the new rule id.
- CloudWatch `NumberOfObjects` and `BucketSizeBytes` (StorageType dimension `StandardStorage`) are flat; no mass expiry yet.

**Day 3-5:**
- CloudWatch `BucketSizeBytes` for the target storage types (for example `StandardIAStorage`, `GlacierInstantRetrievalStorage`) is growing, and `StandardStorage` is falling by a similar amount.
- If expiry is configured, `NumberOfObjects` drops in line with the oldest age band.
- Check the owning team's error dashboards for any spike in `403`/`InvalidObjectState` errors, which indicate a reader trying to fetch an archived object synchronously.

**Day 14:**
- S3 Storage Lens (dashboard "kestrel-org-default") shows the storage class distribution for the bucket matching the plan.
- Post a one-line summary in the #storage-changes thread and close the change ticket.

## 11. Rollback

Rollback means replacing the new rule with a rule that restores the previous behaviour. There is no "undo" button.

1. Announce the rollback in #storage-changes and page the owning team's on-call rotation if a customer-facing service is affected.
2. Plan a new rule with the next version number that restores the previous schedule (or removes transitions entirely). Rule ids only go up; never reuse a version.
3. Apply it with a new or linked `CHG-` number and the same approver rules as any other change.
4. If the problem is urgent, request an out-of-band promotion via break-glass (section 13). Otherwise it goes out with the next Wednesday job.
5. Understand what rollback does **not** do: objects that have already transitioned stay where they are. Getting them back to `STANDARD` requires restores (for archive classes) and copy-in-place, both of which cost money and time. Talk to Storage on-call before starting any bulk restore.

> **Warning:** A rollback does not un-expire anything. Expired objects are gone unless versioning and a noncurrent-version rule keep them. Double-check expiry values before apply; this is the one mistake we cannot fix.

## 12. Postmortem summary: the 2025 Deep Archive retrieval incident

**Incident:** INC-2025-0419. **Severity:** SEV-2 (financial). **Duration:** about 6 weeks before detection.

**What happened.** During the FY25 clean-up, a lifecycle rule was hand-written in the console (not via blobctl) that moved proof-of-delivery photos older than one year into `DEEP_ARCHIVE`. On paper this was a large saving. In practice, proof-of-delivery photos are pulled during customer billing disputes and damage claims, often for shipments well over a year old, and the disputes workflow expected them to be available in milliseconds.

**Impact.**
- Dispute handling broke: the claims tooling timed out waiting for objects that needed a 12-48 hour restore.
- To unblock a backlog of disputes, the team ran bulk expedited and standard restores. Retrieval and request charges for the dispute retrievals came to **about $41K** over six weeks, which wiped out more than a year of the projected savings.

**Root causes.**
- The rule bypassed blobctl, so there was no plan, no approver and no change ticket.
- Nobody checked which services read the bucket, or how.
- There was no policy statement that some data classes must not go to Frozen.

**What changed.**
- All lifecycle rules must be blobctl-managed and go through staging and the weekly promotion job (this runbook).
- The Storage Tiering & Retention Policy gained its "Overrides" section, including the Tier-1 reader rule and data-class caps.
- Exception codes were introduced so every decision *not* to go to Frozen is recorded and auditable.
- The pre-flight checklist (section 4) now requires checking readers and service tiers.

> **Lesson, in one line:** the cheapest storage class is only cheap if nobody needs the data back in a hurry.

## 13. Break-glass, escalation and on-call

**Storage on-call** is the `data-infra-primary` rotation in PagerDuty. They own the weekly promotion job and are the first stop for anything in this runbook.

Escalation path:

1. **#storage-changes**: questions about a specific change, during business hours.
2. **Storage on-call** (`data-infra-primary`): blocked promotions, rollbacks, suspected cost spikes.
3. **Data Infrastructure engineering manager**: disputes about scope or policy interpretation.
4. **FinOps (#finops, #tidewater)**: questions about savings targets, the dashboard or scope.
5. **Legal (`LEGALOPS` queue)**: anything touching retention periods, legal holds or statutory records.

**Break-glass promotion.** Out-of-band promotion is possible only for rollbacks or for changes that stop active customer impact. It requires Storage on-call plus the owning team's storage approver to both agree in the change ticket. Break-glass is never used to hit a Tidewater deadline.

Owning-team on-call rotations are listed on the Storage Architecture & Service Ownership page.

## 14. Known issues (blobctl 1.9)

- **`blobctl status` paging.** In an interactive terminal, `status` output is sent to a pager once it exceeds one screen, and the pager sometimes swallows the last line. If you are pasting into a ticket, pipe it through `cat` or run it from a non-interactive shell.
- **Re-planning a rule id** overwrites the earlier plan without warning. If two people are working the same bucket, coordinate in #storage-changes.
- **blobctl 2.x is rolling out.** Some flags and output formats may change in 2.x. This runbook is written for 1.9 and should be followed as written on 1.9. For 2.x questions or early-access builds, see **#blobctl-dev**; do not mix 2.x habits into 1.9 commands.

## 15. FAQ

**Can I apply without planning first?**
No. `apply` requires a recorded plan for the same rule id and will fail without one.

**The bucket already has a rule. Do I delete it first?**
No. The new rule replaces the old one. Just bump the version number in the rule id.

**The dashboard says "expiry only" for the current rule. Is my new rule v1?**
No. Any current rule counts. Take its version and add 1.

**Who is the approver when the writer service belongs to a different team than the bucket owner?**
The owning team's storage approver. Ownership is per bucket, on the Storage Architecture & Service Ownership page.

**Two exception codes apply. Which do I record?**
The first in precedence order: `STATUTORY_RETENTION`, `TIER1_READER`, `DATA_CLASS_CAP`, `SMALL_OBJECTS`.

**The data class has no expiry. What do I pass for `--expire`?**
Nothing; omit the flag. That is the only case where you leave it out.

**The bucket is marked Exempt but it is costing real money. Can I tier it anyway?**
No. Exempt buckets are never touched. Raise it with FinOps if you think the exemption is wrong.

**When will my change be live?**
After the next Wednesday 14:00 ET promotion job, if no freeze is in effect.


## 16. Revision history

| Date | Version | Author | Change |
|---|---|---|---|
| 2026-07-30 | 4.2 | Storage on-call | Updated for blobctl 1.9; added 2.x rollout note to Known issues. |
| 2026-06-18 | 4.1 | Data Infrastructure | Added Tidewater scope rule and exception precedence order. |
| 2026-04-02 | 4.0 | Data Infrastructure | Rewritten for Project Tidewater; removed console-based steps. |
| 2025-11-14 | 3.3 | Storage on-call | Added month-end close freeze for Billing. |
| 2025-08-27 | 3.2 | Data Infrastructure | Added Deep Archive retrieval incident summary (INC-2025-0419). |
| 2025-05-09 | 3.0 | Data Infrastructure | Introduced staging-first flow and weekly promotion job. |
| 2024-10-21 | 2.0 | Platform | Initial blobctl-based runbook (blobctl 1.4). |
