# v1 implementation handoff — 2026-09-09

## Result

Extended the existing bot in place, preserving the handler → service → repository → SQLite architecture and all original tests. Finished payment editing, disable/reactivate, history-safe deletion, Members, Status, audited admin corrections, Reports, group settings/defaults, Join onboarding, cancel/back navigation, group switching, permission checks, and empty/error states.

Added durable reminder attempt tracking, bounded retries, multipart mentions, concurrent-update serialization, group timezone evaluation, single-process locks, health checks, safe backup/restore and reconciliation commands, startup/shutdown cleanup, and systemd deployment/timers. No real Telegram messages were sent and no production deployment was attempted.

## Verification performed

| Check | Result |
|---|---|
| Initial existing suite | 39 passed |
| After edit/disable/delete | 49 passed |
| After status/settings repository work | 53 passed |
| After navigation/onboarding | 59 passed |
| Routing/concurrency/operations checks | 68 passed |
| Lifecycle/timezone/large-group checks | 71 passed |
| Expanded admin route and wizard checks | 73 passed |
| Final full suite | **75 passed in 3.05 seconds** |
| Syntax compilation | **68 Python files passed** |
| Import without token or network | Passed with Bot construction and socket connections explicitly prohibited |
| Original test files | Every original test file byte-for-byte unchanged |
| Existing database upgrade rehearsal | All original rows preserved on an isolated copy through migrations 1–3 and three initializations; SQLite integrity check passed |
| Live reminder.db | SHA-256 identical before and after; not migrated, deleted, or modified |
| Backup/restore | WAL-aware backup, restore to a separate file, integrity, retention, CLI roundtrip, and overwrite protection tested |

All automated tests used isolated temporary databases and fake/mocked Telegram calls. The original source was snapshotted in the Codex task workspace before edits because this directory has no Git metadata. No Git commit was created.

## Database changes

- Migration 1 retained: existing `reminder_dispatches`.
- Migration 2: `group_settings`, `status_audit`, supporting indexes.
- Migration 3: `reminder_attempts` and `reminder_messages`.
- Existing `group_admins.selected` is reused for preferences; current Telegram permissions are always checked separately.
- No original columns removed or rewritten. Legacy `payment_status.last_reminded_at` retained.
- Existing composite-member-key foreign-key caveat retained. `PRAGMA foreign_keys=ON` was not enabled.
- Migration failures roll back; pre-destructive-migration copies now use a consistent SQLite backup instead of copying a live database file.

Before your first upgraded launch, take a verified backup. Startup applies the pending additive migrations to whichever database DATABASE_PATH names. For production use DATABASE_REQUIRE_EXISTING=true and the offline migrate/backup workflow.

## Important behavior and limitations

- Current counts follow current assignments; historical rows persist after unassignment. Reassignment preserves paid status.
- Currency/time defaults affect new payments; existing payments retain their values. Group timezone changes affect future local-date evaluation.
- Reports show recorded cycle status with current names, not historical amounts or inferred on-time statistics.
- Live old-month buttons are rejected. The explicit-period service interface is preserved for the original tests and internal compatibility.
- Telegram delivery and SQLite cannot be one transaction. Reserved/uncertain attempts suppress blind retries and make health checks fail until an operator reconciles delivery. Known rejections receive bounded retries.
- Single-token locking covers one operating-system user on one host. Do not poll the same token from another host/account.
- SQLite retains its existing journal mode; a five-second lock timeout and short transactions are used. Backups support WAL if explicitly enabled later.

## Remaining live acceptance gates

These are external verification/deployment steps, not claimed as completed:

1. Run the complete MANUAL_TELEGRAM_ACCEPTANCE.md checklist with a test bot and real accounts.
2. Install the supplied systemd units on the chosen Linux host and verify restart/reboot and persistence.
3. Configure an actual monitoring destination and test notification delivery.
4. Configure protected off-host backup transfer, rehearse recovery, and record the production recovery time/data-loss window.

Use DEPLOYMENT.md for exact commands and safeguards. The application code and local verification are complete; production acceptance remains pending these gates.
