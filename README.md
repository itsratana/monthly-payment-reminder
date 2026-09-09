# Monthly Payment Reminder Telegram Bot — Complete v1 Implementation Brief

## Current implementation status — 2026-09-09

The existing codebase has been extended in place. The original requirements below remain as the implementation brief; their historical claims and unchecked acceptance boxes are not a substitute for the current verification record here.

### Implemented and locally verified

- Payment editing with shared validation; disable/reactivate; confirmation-based deletion only for payments without history.
- Members and member details, current Status, audited admin Mark Paid/Unpaid, month-by-month recorded status Reports.
- Group currency/time defaults and timezone settings, Join button onboarding alongside `/join`, complete wizard cancel/back, and remembered per-admin group selection.
- Fresh permission checks on admin actions, private administration, group-scoped member lookup, safe stale callbacks, and live rejection of old-month self-paid buttons.
- Pagination, empty/error recovery, bounded input, current group labels, unpaid mentions, multipart reminders for larger groups, and synchronized status updates.
- Durable dispatch reservation and bounded known-failure retries; uncertain delivery is flagged for explicit offline reconciliation rather than blindly resent.
- SQLite busy timeout, additive migrations, integrity checks, consistent backup/restore tooling, single-owner locks, bounded shutdown, health probes, and a systemd deployment/backup/monitoring setup.

### Verification

- Original baseline: **39 tests passed**. Current full suite: **75 tests passed**.
- All original test files were preserved; new tests cover management, real aiogram routing with a fake Telegram transport, permission rejection, FSM navigation, migrations, concurrency, backup/restore, and lifecycle/health behavior.
- Existing-database migration rehearsal: migrations 1–3 and three repeated initializations on a copy preserved every original row and the legacy `last_reminded_at` column; integrity checks passed.
- The actual `reminder.db` was **not migrated, deleted, or modified** during implementation; its SHA-256 remained identical. Runtime startup applies pending migrations to the configured database, so take a verified backup before your first upgraded launch.
- Final syntax and token/network-free import checks are recorded in IMPLEMENTATION_NOTES.md.

### New migration versions

| Version | Change |
|---|---|
| 1 | Existing `reminder_dispatches` migration retained |
| 2 | `group_settings`, `status_audit`, supporting indexes |
| 3 | `reminder_attempts`, `reminder_messages` for reservation/reconciliation and multipart delivery |

The existing `group_admins.selected` field stores each admin's group preference; it is never trusted as proof of current admin rights. Foreign-key enforcement remains off for the documented composite-key compatibility reason.

### Behavioral details

Current status and reminders use current assignments. Adding an assigned member creates a missing current-cycle row on the next initialization; removing a member excludes them from current counts/reminders but retains historical rows. Re-adding does not reset a paid flag. Reports use retained cycle rows and current display names, without claiming historical monetary values or on-time performance.

Group defaults prefill new payments; existing per-payment currency/time remain intact. A timezone change affects subsequent local-date evaluation and may make a different local day eligible; existing dispatch rows are never deleted. Disabled payments retain history. A status screen may initialize current-cycle rows, so a payment already viewed there can have history even before a reminder is sent.

The framework-neutral paid service retains its explicit-period interface for compatibility with the original tests. The live Telegram handler additionally enforces the message's group and current local month. Ordinary users cannot alter old history through stale Telegram buttons.

### Operator handoff

Read [DEPLOYMENT.md](DEPLOYMENT.md) for exact setup, environment variables, systemd installation, logs, backup/restore, health/alerts, delivery reconciliation, and upgrade/rollback commands. Use [MANUAL_TELEGRAM_ACCEPTANCE.md](MANUAL_TELEGRAM_ACCEPTANCE.md) as the live acceptance checklist.

**Not yet verified:** real Telegram acceptance, production server deployment/reboot, actual monitoring notification delivery, and off-host backup transfer/restore. No production host or monitoring/storage destination was supplied, and no real Telegram messages were sent during implementation. The code and local verification are complete; production acceptance requires those operational gates.

---

## Original implementation brief

## Mission and evidence

Finish the existing bot as a reliable, usable v1 for small private Telegram groups. Implement the remaining management features, verify the existing reminder lifecycle, harden SQLite operations, and supply tested deployment and recovery procedures. Work from the repository as it exists; do not rebuild the bot from scratch.

This brief is based on the “Telegram reminder bot tips” conversation and its completed implementation notes. The repository and live bot have not been inspected while preparing this document. “Completed” below means reported by the previous implementation pass, not independently verified here. Inspect code and tests to establish actual status before changing anything. Earlier incremental snippets in the conversation may be obsolete; do not paste them over newer code.

The product tracks participants’ self-reported payment status. It does not process payments or verify bank transactions. Do not add payment gateways, a web dashboard, PostgreSQL migration, financial analytics, or unrelated features to finish v1.

## 1. Start by inspecting the repository

Before editing:

1. Read repository instructions, the existing README, implementation notes, dependency files, configuration, deployment files, and tests. Preserve useful existing setup documentation when integrating this brief into the repository README.
2. Check the working tree and preserve unrelated work. Locate handlers, keyboards, FSM states, services, repositories, schema/migrations, scheduler, and application startup.
3. Trace `/start`, group selection, `/join`, creation, member assignment, reminder dispatch, and `I've Paid` end to end.
4. Inspect the schema on a safe database copy, including columns, keys, indexes, migration versions, and legacy differences. Do not print personal data or secrets. Do not run exploratory migrations against production.
5. Run the existing tests and import/compile checks. Record baseline results and existing failures before implementation.
6. Produce a concise feature inventory: verified complete, partial, missing, or failing. Identify the smallest compatible changes and then proceed through the implementation order below.

Resolve routine implementation details from existing conventions. Ask only for genuinely missing external access or a consequential product decision that cannot be inferred. Do not stop after a plan or after the core MVP works.

## 2. Reported completed core — preserve and verify

| Area | Previous pass reported |
|---|---|
| Groups and administration | Multiple groups, private admin dashboard, group selection |
| Registration | Group `/join` registers members |
| Payments | Create recurring payment; list/detail screens |
| Assignment | Assign/unassign registered members |
| Monthly lifecycle | Monthly `payment_status` rows; fresh month without overwriting previous months |
| Scheduler | APScheduler-based checks at configured interval; due date/time and timezone handling |
| Reminders | Mention unpaid members; daily reminders until paid; stop when all paid |
| Member confirmation | `✅ I've Paid`; update the same reminder message; remove button when all paid |
| Idempotency | `reminder_dispatches` prevents repeated daily sends, including after restart |
| Calendar edges | Due days 29/30/31 handled according to prior spec; verify short-month behavior |
| Migrations | Versioned `schema_migrations`; initial additive dispatch migration |
| Validation | **39 passing tests**, all Python files compile, `import app` succeeds without token/network |

These are regression requirements. A passing historical test count is not evidence of current correctness or production readiness. Real Telegram acceptance testing was still outstanding in the prior pass.

## 3. Preserve the layered architecture

```text
Telegram updates → Handlers / Keyboards / FSM → Services → Repositories → SQLite
APScheduler → Reminder service → Repositories + Telegram delivery
app.py → configuration, resource setup, lifecycle orchestration
```

- Handlers parse input, acknowledge callbacks, invoke authorization and services, and render responses. Keep SQL and recurring business rules out of handlers.
- Services own validation, group scoping, cycle semantics, permission-sensitive operations, and orchestration. Share status-change logic between member and admin actions.
- Repositories own parameterized SQL and explicit transaction boundaries. Match existing interfaces unless a narrow change is necessary.
- Keyboards/renderers handle consistent labels, navigation, escaping, pagination, and Telegram message limits.
- Keep the existing framework, scheduler, configuration style, and dependency versions unless a demonstrated problem requires change. Inspect actual APIs rather than assuming versions.
- Retain import-safe startup: configuration validation, bot construction, scheduler start, and network calls belong in runtime startup, not module import.

## 4. Database and migration constraints

### Existing compatibility requirements

- `database/schema.py:init_db()` reportedly uses `CREATE TABLE IF NOT EXISTS` for original tables. Existing column shapes must remain compatible.
- A real installation has an extra `payment_status.last_reminded_at` column that the previous pass stopped writing. Preserve it; do not rebuild tables merely to match a fresh schema.
- `database/migrations.py` maintains `schema_migrations(version)`. Migration 1 creates `reminder_dispatches`. Inspect actual definitions before adding subsequent versions; never renumber applied migrations.
- Repeated initialization was previously tested three times against the existing database without changing its data. Preserve repeatability and migration idempotency.
- Prefer additive, versioned migrations. Never delete `reminder.db`, drop history, reset migration tracking, or silently recreate a database to make tests pass.
- The prior migration mechanism makes a timestamped `reminder.db.backup-<timestamp>` copy before migrations marked destructive. Audit that mechanism for live-database safety; a simple file copy is not a sufficient general backup method when WAL or concurrent writes are active.

### Critical foreign-key caveat

**Do not simply enable `PRAGMA foreign_keys = ON`.** Existing `members` has a composite primary key `(user_id, chat_id)`, but `payment_members.user_id REFERENCES members(user_id)` references `user_id` alone. That column is not globally unique. Enabling enforcement as-is produces SQLite “foreign key mismatch” errors and breaks assignment.

Do not add a global unique constraint to `members.user_id`: the same Telegram user must be allowed in multiple groups. For v1, retain compatible behavior and enforce group/member relationships in services and repository queries. Every member join must include the payment’s group context; joining only on `user_id` can duplicate or leak members across groups.

If repairing foreign keys is necessary, design a separate explicit migration with correctly scoped composite references, inspect all affected relationships, back up, validate existing rows, preserve data, and test upgrade/rollback on copies before enabling enforcement on every connection. Do not make this redesign a launch dependency without evidence.

### History and integrity

- Preserve cycle-specific status and dispatch records across edits, disable/reactivate, assignment changes, and group default changes.
- Inspect existing cycle keys; maintain one status per payment/member/year/month and one dispatch per payment/local date for the supported daily policy, with database-enforced uniqueness where compatible.
- Existing `payment_status` does not snapshot payment amounts. V1 reports must show status history without claiming historical amounts, revenue, on-time percentages, or month-end state that cannot be reconstructed.
- If historical names are not snapshotted, clearly label displayed names as current names. Do not describe current configuration as historical fact.
- Audit assignment changes: preserve old rows and paid flags; do not let removing/readding a member reset payment history. Document how additions/removals affect an already-open cycle, current denominators, and future cycles, using explicit service rules and tests.

## 5. Final target UX

Administration takes place in private chat. Ordinary members register and confirm their own status in the group.

```text
🏠 Family Expenses

➕ Add Payment
📋 Payments
👥 Members
📊 Status
📈 Reports
⚙️ Settings
🔄 Switch Group
```

```text
📋 Payments
Netflix • 18 USD • Due 5th
Internet • 25 USD • Due 12th
Rent • 300 USD • Due 1st

💳 Netflix
💰 18 USD
📅 Every 5th
⏰ 09:00
👥 4 members
🟢 Active

👥 Manage Members
✏️ Edit
⏸ Disable / ▶️ Reactivate
🗑 Delete
⬅️ Back
```

Always display the active group and relevant month. Paginate long lists. Every submenu has a valid Back destination; every wizard has Cancel. Avoid dead buttons and placeholder screens.

## 6. Remaining feature requirements

### 6.1 Edit payment

Allow editing name, amount, currency, due day, and reminder time from payment detail. Reuse existing validators and numeric representation; reject blank/oversized names, invalid or nonpositive amounts, unsupported currency input, days outside 1–31, and invalid times. Avoid introducing floating-point rounding errors.

Show current values, validate before save, and return to refreshed detail with clear success feedback. Cancel writes nothing. Recheck permissions and payment/group ownership at save time.

Edits update recurring configuration without resetting paid flags, deleting dispatches, or rewriting earlier cycles. Explain the effective schedule in the UI; default to applying configuration to future evaluations while respecting already-recorded daily dispatches. Test a due-time/day edit after a reminder has already been sent. Do not claim an old cycle had the newly edited amount.

### 6.2 Disable and reactivate

Use the existing `active` field if present. Disabled payments create no new cycles and send no reminders; history remains accessible. List active and disabled entries clearly, with a filter or separate section.

Reactivate without resetting existing status or dispatch records. Evaluate the current month under normal due-date rules; do not flood the group with missed-day messages. Confirm disable/reactivate results and make repeated actions harmless. Refresh or invalidate stale message controls consistently; a disabled payment must not continue normal reminder activity through an old callback.

### 6.3 Safe delete

Make Disable the normal retirement path. Delete is admin-only, uses an explicit confirmation naming the payment and consequences, and supports cancellation. Revalidate the target when confirmation is submitted.

Default policy: physically delete only an unused payment with no status/dispatch history; remove its configuration/assignment records transactionally. If history exists, offer Disable or implement an additive archived/tombstone state that hides it from normal lists while retaining report links. Never cascade away history silently. Distinguish archival from permanent deletion in UI text. Replayed or stale confirmations must be safe.

### 6.4 Members screen

List members registered in the selected group, using full name and optional username. Show a member’s assigned payments and current paid/pending state. Handle users without usernames and profile updates on repeat registration. Provide an onboarding action when the list is empty.

Member removal is optional for v1. If exposed, define removal as leaving active participation without erasing past status. Never remove a user’s registration in another group.

### 6.5 Current status screen

Show the current month in the group’s effective timezone, each relevant payment, paid/total counts, and pending members. Open a payment to view Paid and Pending lists and admin correction actions. Distinguish disabled payments and not-yet-due payments. A payment with no assigned members is “No members assigned,” not a successful collection.

Read existing cycle data consistently. If status viewing materializes a cycle, use the same idempotent service as the scheduler; never reset flags. Denominators must follow the documented assignment/cycle policy.

### 6.6 Admin mark paid / mark unpaid

Allow an authorized group admin to correct a selected member’s status for the displayed current cycle. Require an explicit member and action; show the result. Ordinary members can mark only themselves paid through the existing member flow.

Use transactional, idempotent operations. Record actor, target, payment, cycle, old/new status, and timestamp through a minimal additive audit mechanism if the existing schema cannot retain this information. Do not invent original payment timestamps when importing legacy data.

Refresh the relevant reminder message after a correction where possible. Mark Unpaid resumes eligibility under the normal schedule without deleting daily dispatch protection or causing an immediate duplicate send. Failure to edit a Telegram message must not undo a successfully saved correction. Historical corrections are outside v1 unless already supported; do not accidentally apply current actions to old cycles.

### 6.7 Reports and history

Provide month/year selection and per-payment completed/total counts with paid/pending members from retained `payment_status`. Include disabled/archived payments with history. Show a useful empty state and month navigation.

Do not infer past totals from today’s assignment list. Unless timestamps/audit data prove otherwise, label values as recorded cycle status rather than “pending at month end” or “paid on time.” Keep v1 to reliable status history; no advanced financial metrics or exports are required.

### 6.8 Group settings

Add persistent group-specific default currency, IANA timezone, default reminder time, and reminder policy. Validate all fields and display effective values. Group defaults prefill new payment creation; retain existing per-payment currency and reminder time and permit overrides.

Do not bulk-rewrite existing payments when defaults change. Use group timezone when explicitly set, otherwise `APP_TIMEZONE`; preserve existing behavior for groups without settings. Explain that changing timezone changes future schedule evaluation, and test local-date/dispatch behavior across the change.

The existing `REMINDER_POLICY` setting was documented for future switching; implemented behavior was always `daily_until_paid`. Support that policy honestly in v1. Do not offer selectable policies with no implementation. Define precedence and reject unsupported settings clearly rather than implying they work.

### 6.9 Join button onboarding

Provide a group onboarding message:

```text
👋 This group uses Monthly Payment Reminder.
Tap below to participate.

[✅ Join Payment Tracking]
```

The button and `/join` call the same registration service, using the actual Telegram actor and group context. Registration is idempotent, refreshes profile details, and never trusts an arbitrary user ID from callback data. A normal member can join without admin rights. Provide an admin action to post onboarding deliberately; do not spam on every dashboard visit. Explain how admins open the private dashboard without assuming the bot can initiate private chats.

### 6.10 FSM cancel/back and creation polish

Add `❌ Cancel` and `/cancel` at every creation/edit/settings wizard step. Clear FSM data and return to a valid screen. Back returns to the previous step with sensible entered values retained. Validate only the field being entered; unrelated commands must not become field values.

Do not leave partially created payments on cancel or invalid input. On restart/stale wizard, show a clear recovery path. Recheck group/admin scope at completion. After creation, show a summary and `👥 Manage Members` / `⬅️ Dashboard` buttons. Group defaults should reduce repetitive questions without removing per-payment configuration compatibility.

### 6.11 Switch-group polish

Remember active group per admin persistently if not already supported. Show only groups the user is currently authorized to administer. Handle no groups, one group, deleted/inaccessible groups, and lost admin rights.

Switching clears or safely abandons any active wizard. Old keyboards must not execute against the newly selected group accidentally: resolve the object’s actual group and validate authorization. Two admins must have independent selections.

### 6.12 Permission hardening

Audit every command, callback, wizard completion, and repository-backed mutation. Button visibility is not authorization. Check current Telegram group-admin status at meaningful action boundaries, including final confirmation. Bound any cache so revocation is respected; fail closed for privileged mutations if verification fails.

Verify actor, selected/target group, payment ownership, member registration/assignment, and cycle. Prevent cross-group access through forged IDs and stale callbacks. An `I've Paid` callback must identify its original payment/cycle and the clicking user; never reinterpret an old-month button as payment for the current month. Answer expired/unauthorized callbacks helpfully without exposing another group’s data.

## 7. Reminder-engine audit

Preserve the working engine and add targeted regression tests for:

- Local due day/time, before/after cutoff, year rollover, leap years, and clamping days 29/30/31 to the last valid day of shorter months.
- One new monthly cycle with unpaid status for eligible members; previous months remain unchanged.
- Only active payments and eligible pending members are reminded. No empty-member reminders or reminders after all paid.
- Once-per-local-day daily reminders from due time until paid within the current cycle. After downtime, evaluate current eligibility once; do not replay every missed tick/day. Do not introduce old-month arrears reminders without an explicit requirement.
- Correct username mentions and escaped tappable name links for users without usernames. Respect Telegram text/button limits and rate limits.
- `I've Paid` only changes the actor’s authorized cycle row; rapid repeated clicks are harmless. Refresh the same message and remove controls when everyone is paid.
- Restart and concurrent-tick protection via `reminder_dispatches` and scheduler overlap controls. Status updates, assignment edits, disable, and dispatch must not race into inconsistent state.
- Telegram failures: rate-limit retry delay, transient failures, blocked/kicked bot, unavailable group, deleted messages, stale callbacks, and “message is not modified.” A message-render/edit failure must not lose a saved paid state.

Audit precisely when a dispatch is reserved, sent, and marked successful. A reservation before send can suppress a reminder after a crash; recording only after send can duplicate delivery after a crash. SQLite and Telegram cannot share an atomic transaction, so do not claim absolute exactly-once delivery. Preserve normal restart idempotency, define bounded retry/reconciliation for failed or uncertain sends, avoid blind resends after ambiguous delivery, and document the remaining crash window. Do not hold database write transactions open during network calls.

Run one polling bot and one scheduler owner per token/database. Do not use multiple replicas as a shortcut to availability.

## 8. Empty states, errors, and logging

Provide clear responses for no groups, no members, no payments, no history, no pending members, missing/deleted targets, expired actions, invalid input, and unavailable Telegram permissions. Offer the relevant next action and Back. Acknowledge callbacks promptly so buttons do not spin indefinitely.

Catch expected errors near their boundary and log unexpected errors with stack traces. Keep one bad payment/group from terminating the scheduler. Avoid blanket exception swallowing and misleading success messages.

Use `LOG_LEVEL` consistently. Log startup/shutdown, migration versions, scheduler heartbeat, dispatch outcomes, permission denials, state corrections, and recoverable/fatal errors with group/payment/cycle identifiers where useful. Never log bot tokens, `.env` contents, full private messages, or unnecessary member details. Configure log rotation/retention and prevent repetitive failures from flooding logs.

## 9. Configuration and local verification

Preserve the existing environment variable names and documented defaults unless repository evidence requires a corrected explanation:

| Variable | Existing default | Required behavior |
|---|---|---|
| `BOT_TOKEN` | Required | Validate at runtime; never commit or log it |
| `APP_TIMEZONE` | `Asia/Phnom_Penh` | Valid IANA fallback timezone |
| `REMINDER_CHECK_SECONDS` | `60` | Positive scheduler tick interval |
| `DATABASE_PATH` | `reminder.db` | SQLite path; persistent absolute path recommended in production |
| `REMINDER_POLICY` | `daily_until_paid` | Previously informational; only advertise supported behavior |
| `LOG_LEVEL` | `INFO` | Valid logging level |

Retain `.env` support if present and provide a secret-free `.env.example`. Exclude secrets, databases, WAL/SHM files, and backups from Git. Validate configuration with actionable messages before starting polling.

Previously documented setup (verify against current repository):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -c "import app"
python3 app.py
```

The previous pass reported **39 tests passed**, `python3 -m py_compile <all project .py files>` succeeded, and `import app` required neither `BOT_TOKEN` nor network. Rerun equivalent checks on actual project files, excluding virtual environments. Tests must use temporary SQLite databases (`tmp_path` and monkeypatched `config.DATABASE_PATH`, as before), never the real `reminder.db`. Report new results accurately rather than repeating the historical count.

## 10. SQLite production hardening and backups

- Use persistent local storage with known ownership, restricted permissions, adequate space, and an explicit database path. An ephemeral container filesystem is unacceptable.
- Centralize connection options and cleanup. Configure bounded busy timeout and short transactions; handle locks without infinite retries or blocking the async event loop unnecessarily.
- Evaluate WAL for the actual deployment filesystem and workload. If enabled, configure durability deliberately and include WAL-aware backup/recovery. Do not enable foreign keys without resolving Section 4.
- Add only justified indexes for cycle, group, pending-status, and dispatch queries. Test concurrency and transaction rollback using realistic fixtures.
- Fail clearly for unwritable storage, corruption, failed migrations, or accidental missing-volume paths. Avoid silently booting a new empty production database.

Provide a runnable backup command/script using SQLite’s online backup API or another demonstrated consistent method. Schedule at least daily backups and a pre-upgrade backup. A proposed default is 7 daily and 4 weekly retained backups; make schedule, location, retention, and expected data-loss window explicit and adjustable.

Store backups separately from the live database, with a protected off-host copy where deployment access permits. Rotate only after a new backup is verified. Monitor backup success, age, and failures. A successful copy alone is not proof of recoverability.

Supply and rehearse a restore runbook: stop the bot/scheduler, preserve the current failed database and related files, restore a verified backup with correct permissions, run integrity/schema checks, restart exactly one instance, and verify members, history, and dispatch protection. Never restore over a running writer. Measure and record restore time; disclose that restoring an older backup may lose recent paid/dispatch records and require reconciliation. Rehearse on a temporary path without sending production reminders.

## 11. Startup, shutdown, deployment, and monitoring

### Application lifecycle

At startup: validate config and storage, initialize/migrate safely, initialize resources, verify readiness, and start a single scheduler/polling owner. Handle partial startup failure by closing resources. Importing modules must remain side-effect free.

On SIGINT/SIGTERM: stop scheduling new work, stop intake, allow bounded completion/cancellation of in-flight work, persist dispatch outcomes where known, close Telegram sessions and database resources, and exit cleanly. Fatal startup/runtime failures should return a failure status for the supervisor.

### Deployment deliverables

Inspect existing deployment files and complete one concrete supported path, such as systemd on a VPS or Docker Compose with a persistent volume. Do not add multiple unfinished deployment systems. Include exact setup/start/stop/status/log/upgrade/rollback instructions, dependency installation, protected environment loading, timezone data, non-root execution where practical, and restart-on-failure/reboot behavior.

Document how to prevent duplicate polling processes during upgrades, preserve the volume, back up before migrations, and match application rollback to schema compatibility. Do not expose unnecessary public ports for a polling bot.

### Health and monitoring

Provide a lightweight health mechanism appropriate to the chosen deployment: command, timestamp/state file, or a minimal protected endpoint. Check more than process existence: startup completed, database reachable, scheduler tick recent, and polling/service activity healthy. Lack of user messages must not itself signal failure.

Monitor process restarts, stale scheduler heartbeat, repeated Telegram delivery failures, database locks/errors, disk capacity, and backup freshness. Configure actionable alerts and bounded restart behavior. Explain who receives alerts and how to diagnose a failed check. Do not log a healthy heartbeat at noisy frequency.

Deployment or live testing requiring unavailable credentials, a host, or accounts must be reported as blocked with exact remaining steps. Complete all locally testable work first. Never claim live deployment, alerts, or restore verification that was not performed.

## 12. Automated test requirements

Preserve existing tests and add focused tests proving new behavior:

| Area | Minimum evidence |
|---|---|
| Migrations | Fresh DB, legacy extra column, repeat init, preserved rows, failure rollback, backed-up destructive path if used |
| Multi-group safety | Same user in two groups; no duplicate joins/leaks; forbidden cross-group callbacks |
| Management | Valid/invalid edits, canceled save, disable/reactivate, history-safe delete, replayed confirmation |
| Cycles/history | New month, year/leap/short-month boundaries; assignment changes; no rewritten historical facts |
| Status actions | Self-paid/admin corrections, permission revocation, repeated/concurrent clicks, stale-month buttons |
| Settings/FSM | Defaults and overrides, invalid timezone/time, cancel/back at each step, switch-group during wizard |
| Reminders | Unpaid-only, all-paid stop, same-message edits, daily uniqueness/restart, concurrent ticks, failure windows |
| Operations | Config validation, import safety, graceful shutdown, lock handling, backup and restore integrity, health staleness |

Use an injected/frozen clock and mocked Telegram API for deterministic automated tests. Never change the host clock, use real tokens, or send real messages from the ordinary test suite. Run required repository checks and summarize actual outcomes and any unresolved failures.

## 13. Manual Telegram acceptance test

Run in dedicated test groups with a real test bot and two member accounts; use a second group and an unauthorized account for isolation tests. Record date, app revision, scenario, expected/actual result, and sanitized evidence. Automated tests do not replace these steps.

1. Start with valid configuration. Verify a missing token fails clearly and a normal startup creates only one scheduler/poller.
2. Register two members using `/join` and the Join button, including repeat clicks and a member without a username. Confirm group-specific registration.
3. Open private `/start` as admin, select the group, and inspect all dashboard destinations and empty states.
4. Create a payment due today with a reminder time 1–2 minutes ahead in the effective timezone; assign both members. Confirm exactly one reminder after the scheduler tick and correct mentions.
5. Member A taps `✅ I've Paid`: only A becomes paid; the same message updates, B stays pending, and feedback appears. Repeat the click safely.
6. While B remains pending, restart the bot. Confirm no duplicate reminder for the same local day/payment.
7. Verify the next local day’s reminder mentions only B. Use an isolated test clock/environment for acceleration, never change the production host clock or corrupt production dispatch rows.
8. Member B pays. Confirm all-paid text, removal of the button, and no further reminders. Verify unauthorized/non-assigned clicks cannot change status.
9. Use admin Mark Unpaid then Mark Paid. Confirm persistence and message refresh; no same-day duplicate from the correction.
10. Edit each payment field, cancel an edit, disable, and reactivate. Confirm scheduling and history rules. Exercise safe deletion for both unused and historical payments.
11. Check Members, Status, and previous-month Reports. Exercise settings/defaults, per-payment overrides, cancel/back at every wizard step, and remembered group selection after restart.
12. Exercise a second group, revoked admin privileges, stale keyboards, and a group switch mid-wizard. Confirm no cross-group changes.
13. Test deleted reminder messages and bot permission loss in a test group. Confirm useful errors, durable paid state, recovery, and continued service for other groups.
14. In an isolated test environment, advance an injected clock through the next month and 29/30/31/leap-year edges. New cycle starts unpaid; old rows remain unchanged; old buttons cannot mark the new cycle paid.
15. Restart/reboot the deployment, verify persistence and single ownership, exercise graceful shutdown and health failure detection, then restore a backup to a separate test path and verify data.

If a scenario cannot be exercised, mark it unverified with the reason. Do not silently count it as passed.

## 14. Implementation order and working rules

1. Inspect repository, establish baseline, and document schema/cycle/permission invariants.
2. Implement Edit Payment with shared validation and regression coverage.
3. Implement Disable/Reactivate and history-safe Delete.
4. Complete Members and Current Status screens.
5. Add admin Mark Paid/Unpaid with shared status logic and auditability.
6. Add truthful Reports/history.
7. Add compatible Group Settings and default-prefilled creation.
8. Add Join button onboarding.
9. Finish FSM cancel/back and switch-group persistence/navigation.
10. Complete permission, reminder-engine, concurrency, empty/error-state, and logging audits. Apply essential permission checks throughout earlier steps, not only here.
11. Finish SQLite hardening, consistent backup/restore tooling, startup/shutdown, health checks, and deployment configuration.
12. Run the full automated suite and real Telegram acceptance tests; fix failures.
13. Deploy the tested revision where access is available; verify restart/reboot, backups, restore rehearsal, monitoring, and operational handoff.

Work in small coherent changes within existing layers. Add migrations before code depending on new fields. Reuse validators/renderers/repositories; avoid broad refactors and unnecessary dependencies. Never weaken tests, bypass permissions, discard data, or fabricate results to reach completion. Keep configuration secrets outside Git and keep tests isolated from live data. State material assumptions and remaining limitations clearly.

Update the README and relevant runbooks to reflect actual final behavior, effective settings, migration versions, known limitations, and exact operational commands. Preserve prior implementation notes as historical evidence rather than silently converting them into current validation claims.

## 15. Production acceptance criteria and definition of done

V1 is complete only when all applicable items have evidence:

- [ ] Reported core features are reverified and regressions fixed.
- [ ] Every dashboard destination works, including edits, disable/reactivate, safe delete, members, current status, admin corrections, history, settings, and switching groups.
- [ ] `/join` and Join button onboarding share correct group-scoped registration.
- [ ] Every wizard supports cancel/back with no partial writes or stale-group mutations.
- [ ] All privileged actions enforce current authorization; member actions cannot affect other users or cycles.
- [ ] Monthly history survives edits, assignment changes, retirement, migrations, and restarts.
- [ ] Reminders follow documented timezone/calendar/daily rules, mention only pending members, and preserve normal restart idempotency; delivery ambiguity is documented.
- [ ] Legacy databases upgrade without data loss, repeated initialization is safe, and the composite-key foreign-key caveat is respected or safely migrated.
- [ ] Current tests pass, all project Python files compile, and `import app` succeeds without token/network; actual results are recorded.
- [ ] Real Telegram acceptance scenarios pass with recorded evidence.
- [ ] Production uses persistent storage and exactly one bot/scheduler owner, with graceful lifecycle and automatic restart.
- [ ] Scheduled consistent backups run; a restore rehearsal succeeds; retention and recovery steps are documented.
- [ ] Health monitoring and failure alerts are configured and exercised; logs are useful and secret-free.
- [ ] Setup, configuration, upgrade/rollback, backup/restore, and troubleshooting instructions are usable by the operator.
- [ ] No required feature remains a placeholder and no unresolved data-loss, security, or reminder correctness issue remains.

Final handoff must summarize implemented changes, migrations and compatibility, automated test results, manual/live evidence, deployment location/method if actually deployed, backup/monitoring status, and any blockers. Distinguish **implementation complete**, **acceptance verified**, and **deployed/operational**. If access prevents the last stages, deliver the finished code/runbooks and exact outstanding actions, but do not label the project production-ready until the operational gates pass.
