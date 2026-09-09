# Manual Telegram v1 acceptance checklist

Status: **Not performed in this implementation session.** Automated tests use fake Telegram transport and temporary databases. Use a dedicated test bot, two test groups, two participating accounts (one without a username), an admin, and a non-admin. Do not reuse a token already being polled elsewhere.

Record the tested revision/release, date, scenario, expected/actual result, and sanitized evidence. Leave untested items unchecked.

## Setup and onboarding

- [ ] Start with missing/invalid configuration: receive an actionable startup error. With valid configuration, one polling process and one scheduler start.
- [ ] Add the bot to a test group with permission to send/edit its messages and verify member/admin status. Run `/join` from two accounts.
- [ ] Open private `/start` as an admin. Select the group and verify its real name appears.
- [ ] Open Members and deliberately post the Join button. Join/rejoin through it; confirm a single registration and refreshed display name. Private `/join` must explain that registration belongs in a group.
- [ ] Confirm the ordinary member cannot use admin screens, forged/stale admin buttons, or another group's payment IDs.

## Payment management and navigation

- [ ] Create a payment due today, with reminder time 1–2 minutes ahead in the group's timezone. Use group currency/time defaults and assign both members.
- [ ] Reject blank/long names, nonpositive/NaN/infinite amounts, more than two decimals, invalid currency format, day 0/32, and invalid time.
- [ ] At every creation step, exercise Back and Cancel or `/cancel`. Earlier values remain when going back; cancel creates no payment. Nontext messages and unrelated commands do not become field values.
- [ ] Edit name, amount, currency, due day, and time; verify success and invalid-input recovery. Back/Cancel leaves the old value unchanged.
- [ ] Disable the payment: no new cycles/reminders or self-paid changes through stale controls. Reactivate: previous status/dispatch protection remains; no backlog flood.
- [ ] Delete an unused payment after confirmation, cancel another deletion, and replay an old confirmation. Attempting to delete a payment with history must offer Disable instead and preserve all history.
- [ ] Switch groups during creation/edit/settings. No abandoned wizard continues in the other group. Restart and verify remembered group per admin. Revoke admin privileges and confirm further actions are denied.
- [ ] Exercise all empty states, Back destinations, and pagination with more than eight records. No placeholder buttons should remain.

## Reminder lifecycle

- [ ] After the configured tick, exactly one reminder appears for the local day/payment. Both pending members are mentioned, including a tappable name for the account without a username.
- [ ] Member A taps `✅ I've Paid`. Only A becomes paid; the same message updates to leave B pending. Repeated clicks are harmless.
- [ ] Restart while B remains pending. No duplicate reminder appears for the same payment/local day.
- [ ] On the next local day, B alone is mentioned. Use an isolated injected-clock test environment if accelerating time; never change the production host clock or delete production dispatch rows.
- [ ] Member B pays. The message becomes all-paid, buttons disappear, and further reminders stop.
- [ ] Have both accounts click close together. The final message and stored status agree.
- [ ] Admin marks a current member Unpaid then Paid. Check audit data offline, stable history, correct message refresh, and no immediate same-day duplicate.
- [ ] Remove and re-add a member. Current counts/reminders follow current assignments; historical rows and existing paid flags are preserved.
- [ ] For a large group, check multipart reminders remain within Telegram limits and collectively mention everyone pending.

## Status, history, and settings

- [ ] Members shows assigned payments and current status; Status shows paid/total, pending members, disabled/not-yet-due states, and “No members assigned” where appropriate.
- [ ] Reports navigates months and shows recorded rows, including disabled payments. Names are identified as current; no unsupported historical amounts or on-time claims appear.
- [ ] Group currency/time defaults prefill new payments without changing existing ones. Timezone changes affect that group's future evaluations only; understand that a changed local date can allow a reminder on that date.
- [ ] In an isolated test environment, cross a month/year boundary and February/leap-year/29/30/31-day cases. A fresh cycle starts unpaid; old history survives. Old-month Telegram buttons cannot update the current cycle or rewrite old history through the live handler.

## Failure and production checks

- [ ] Delete a reminder message or revoke the bot's send/edit permission in one test group. Saved payment status remains durable; errors are useful; other groups continue working.
- [ ] Exercise a known rejection/rate-limit and an uncertain send in controlled tests. Retries are bounded; uncertain delivery requires operator reconciliation rather than a blind resend.
- [ ] Start a second process against the same database/token under the deployment account. It must refuse to run.
- [ ] Stop with SIGTERM/Ctrl+C, restart, and reboot the host. Verify graceful closure, persistence, supervisor restart, and a single owner.
- [ ] Trigger a stale heartbeat and confirm the health check fails and the operator receives the configured alert. Verify missing/old backups and low disk are detectable.
- [ ] Run the backup timer, verify retention and off-host copy, restore to a separate path, and check data/history/dispatch records. Record recovery time and reconcile any backup-age gap.

Do not mark production accepted until every required live/operational scenario passes. See DEPLOYMENT.md for commands and recovery procedures.
