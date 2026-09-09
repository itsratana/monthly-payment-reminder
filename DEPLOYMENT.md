# Deployment and recovery runbook

## Status and supported deployment

The supported deployment is a single Linux systemd service running Python 3.12 on a VPS with a persistent local disk. This repository includes the service, backup timer, health timer, and operational commands. They have not been installed on a production host in this implementation session. The local database has not been migrated or modified. Live Telegram acceptance, host restart/reboot, off-host backup transfer, and actual notification delivery remain operator acceptance gates.

Keep exactly one bot process for a token. The application locks both the database and a token-specific file for its lifetime. Token locks are scoped to the operating-system user on the same host: deploy under the single `paymentbot` account, and do not run the same token from another host/user. A database lock also prevents two local processes sharing a database. Never run development polling with the production token while the service runs.

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env
```

Edit `.env` and supply your token privately. Keep existing `.env` files; do not overwrite an already-configured file. Run `python -m pytest -q` before deployment. Start with `python app.py`. Module imports do not validate the token, start the scheduler, or contact Telegram.

Configuration remains compatible:

| Variable | Default / meaning |
|---|---|
| BOT_TOKEN | Required at runtime; never log/commit it |
| APP_TIMEZONE | Asia/Phnom_Penh; fallback for groups without an explicit timezone |
| REMINDER_CHECK_SECONDS | 60; positive scheduler interval |
| DATABASE_PATH | reminder.db; use an absolute persistent path in production |
| REMINDER_POLICY | daily_until_paid; other policies fail validation |
| LOG_LEVEL | INFO |
| DATABASE_REQUIRE_EXISTING | false for initial local use; **true in production** to reject missing storage |
| HEALTH_PATH | DATABASE_PATH + `.health.json`; writable by the bot user |
| BACKUP_DIRECTORY | Empty locally; set the backup directory in production so health checks enforce freshness |
| MONITOR_WEBHOOK_URL | Optional HTTPS endpoint accepting JSON `{ "text": "..." }`; configure privately for health alerts |

Amounts accept positive values up to 999999999.99 with at most two decimal places. Decimal validation precedes storage in the existing REAL column for compatibility; the bot performs no financial arithmetic. Currency input is a three-letter alphabetic code; it is not an exchange-rate or payment-processing integration.

## Install on the server

Use your host's package manager to install Python 3.12 with venv support, CA certificates, and timezone data. Copy the tested source and pinned requirements to `/opt/payment-reminder`; do not copy the Mac virtual environment. Create a dedicated account and storage directories:

```bash
sudo useradd --system --home /var/lib/payment-reminder --shell /usr/sbin/nologin paymentbot
sudo install -d -o paymentbot -g paymentbot -m 0700 /var/lib/payment-reminder /var/backups/payment-reminder
sudo python3.12 -m venv /opt/payment-reminder/.venv
sudo /opt/payment-reminder/.venv/bin/pip install -r /opt/payment-reminder/requirements.txt
sudo install -o root -g paymentbot -m 0640 /opt/payment-reminder/.env.example /etc/payment-reminder.env
```

Edit `/etc/payment-reminder.env` securely. Set:

```dotenv
BOT_TOKEN=YOUR_REAL_TOKEN
DATABASE_PATH=/var/lib/payment-reminder/reminder.db
DATABASE_REQUIRE_EXISTING=true
HEALTH_PATH=/var/lib/payment-reminder/health.json
BACKUP_DIRECTORY=/var/backups/payment-reminder
APP_TIMEZONE=Asia/Phnom_Penh
REMINDER_CHECK_SECONDS=60
REMINDER_POLICY=daily_until_paid
LOG_LEVEL=INFO
```

Configure `MONITOR_WEBHOOK_URL` for a real monitored destination, or arrange external monitoring of failed service units. Do not store the real URL in Git.

### Preserve an existing installation

Stop the old polling process first. Create a consistent backup, transfer it securely to the server, and restore to a **new, nonexistent** destination:

```bash
python -m ops --db /absolute/path/to/existing/reminder.db backup --directory /absolute/path/to/transfer-backups
cd /opt/payment-reminder
sudo -u paymentbot .venv/bin/python -m ops restore --source /secure/staging/verified-backup.db --destination /var/lib/payment-reminder/reminder.db
sudo -u paymentbot .venv/bin/python -m ops --db /var/lib/payment-reminder/reminder.db migrate
```

Substitute the actual generated backup filename. The source must be readable by `paymentbot`. Restore never overwrites an existing destination. Do not copy just the live `.db` file while WAL writes are active.

Only for a genuinely new installation with no data to preserve:

```bash
cd /opt/payment-reminder
sudo -u paymentbot .venv/bin/python -m ops --db /var/lib/payment-reminder/reminder.db init
```

`init` refuses an existing database. `migrate` refuses a missing one and makes a consistent pre-migration backup. Startup also runs additive migrations, so deploy only after testing the migration on a copy and taking a pre-upgrade backup.

### Enable services

```bash
sudo cp /opt/payment-reminder/deploy/payment-reminder*.service /etc/systemd/system/
sudo cp /opt/payment-reminder/deploy/payment-reminder*.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/payment-reminder*.service /etc/systemd/system/payment-reminder*.timer
sudo systemctl daemon-reload
sudo systemctl start payment-reminder-backup.service
sudo systemctl enable --now payment-reminder.service payment-reminder-backup.timer payment-reminder-health.timer
```

Verify unit syntax on the actual Linux host; systemd is not available on the development Mac. No public inbound port is needed for long polling. Ensure outbound HTTPS to Telegram and the monitoring endpoint is allowed.

## Routine operations

```bash
sudo systemctl status payment-reminder.service
sudo journalctl -u payment-reminder.service -n 100 --no-pager
sudo systemctl stop payment-reminder.service
sudo systemctl start payment-reminder.service
sudo systemctl restart payment-reminder.service
sudo systemctl list-timers 'payment-reminder*'
sudo systemctl start payment-reminder-backup.service
sudo systemctl start payment-reminder-health.service
```

The bot handles SIGINT/SIGTERM, pauses new scheduler work, allows a bounded in-flight send to finish, closes its HTTP session, and releases locks. The supervisor restarts failures after 10 seconds, limited to five starts per five minutes. After resolving a repeated startup failure, use `systemctl reset-failed payment-reminder` before restarting.

Journald receives application logs. Configure host journald retention, for example `SystemMaxUse=200M` and `MaxRetentionSec=14day` in a dedicated `/etc/systemd/journald.conf.d/payment-reminder.conf`, then restart journald according to your host policy. These limits apply to the host journal, so coordinate with other services. Bot tokens are redacted from formatted application logs; do not paste raw environment files into tickets.

## Health and alerts

The health timer runs every five minutes and checks readiness, recent successful Telegram polling (not incoming user messages), recent scheduler evaluation, database query access, delivery uncertainty/exhausted retries, backup age, and disk space. The scheduler threshold is the larger of three tick intervals and 180 seconds; the polling threshold is 180 seconds. Less than 100 MiB free is unhealthy.

Health returns a nonzero exit status on failure. With `MONITOR_WEBHOOK_URL`, it also posts an alert containing error categories, without private member data. Without a configured endpoint, failures are logged and must be watched by an external host monitor. Verify notification delivery with an isolated stale health file and a real monitored endpoint before calling deployment complete. Monitor service restart counts and journal lock/storage errors through your host monitor as well; the app does not provision an external monitoring account.

```bash
python -m ops --db /path/to/test.db health --state /path/to/test-health.json --backups /path/to/backups
```

The process being alive is not sufficient. If polling or the scheduler is stale, inspect logs, token conflicts, network access, and database locks before restarting. Repeated restarts will not repair an invalid token, missing persistent volume, corruption, or a removed bot.

## Backups and recovery objectives

The backup timer runs at approximately 02:00 UTC daily, catches up after downtime, and uses SQLite's online backup API. Backups are integrity-checked, created with mode 0600, and retained only after a successful new copy. It keeps the latest seven daily backups and one backup per ISO week for the latest four weeks. Extra manual runs count toward the seven most recent daily copies; adjust retention if you need seven distinct calendar days.

Expected local data-loss window is up to about 24 hours after a successful daily backup, and longer if backups fail. Health flags backups older than 36 hours. Recovery time depends on host/storage access; measure it during the actual server rehearsal. A small-database restore was verified locally, but that is not a measured production recovery guarantee.

A copy on the same disk does not cover host/disk loss. Configure protected off-host transfer using your existing storage provider, encryption/access policy, and monitoring. No storage account or destination was supplied, so this step remains an explicit deployment gate. Verify both local and off-host restore before launch.

### Restore rehearsal and incident recovery

1. Stop `payment-reminder.service` and stop the health timer during planned recovery to avoid intentional downtime alerts. Confirm no manual bot is running.
2. Preserve the current database and any `-wal`/`-shm` files together in a timestamped incident directory while no writer is running. Do not delete them.
3. Restore a known verified backup to a **separate new path** using `ops restore`. The command validates integrity and refuses overwrite. Rehearse on a temporary path first.
4. Inspect migration versions and representative member/status/dispatch counts offline. Do not expose member data in logs. Run `ops migrate` if the selected application version needs newer additive migrations.
5. Point `DATABASE_PATH` to the restored file and update `HEALTH_PATH` as appropriate, or safely move the verified restored file into the original path after preserving the old files. Ensure correct owner and mode.
6. Start exactly one service. Verify readiness, group selection, history, and scheduler behavior; re-enable the health timer.
7. Record elapsed recovery time and reconcile paid/dispatch changes since the backup. Restoring an older backup can lose recent payment confirmations or duplicate protection. Review expected reminders before resuming polling.

## Uncertain reminder delivery

`reminder_dispatches` retains the original daily uniqueness contract. Migration 3 adds `reminder_attempts`: a durable reservation is made before sending. Successful multipart message IDs are recorded in `reminder_messages`. Only a fully successful send set is recorded as dispatched.

Known Telegram rejections (including rate limits) receive at most three attempts for that payment/date, honoring retry delay. Unknown failures/timeouts and partial multipart sends become `uncertain`. A crash during a send may leave `reserved`. These cases deliberately suppress automatic retries for that date and trigger health warnings. There is no atomic transaction spanning SQLite and Telegram, so absolute exactly-once delivery cannot be guaranteed.

Stop the bot and inspect the group and relevant attempt/message records. If the message was delivered, acknowledge it as sent. If you have verified that **no part was delivered**, permit a retry:

```bash
python -m ops --db /absolute/path/reminder.db reconcile --payment 123 --date 2026-09-09 --outcome sent
python -m ops --db /absolute/path/reminder.db reconcile --payment 123 --date 2026-09-09 --outcome retry
```

Choose exactly one outcome; the above are alternatives, not consecutive steps. Never blindly retry a partial send. Mark it sent to suppress duplication and resolve any missing information manually in the group. Reconciliation is local, offline, and protected by the instance lock. The next local day remains independently eligible under the normal daily policy. A `sent` acknowledgement suppresses that attempt even if its Telegram message ID was lost in the crash.

## Upgrade and rollback

1. Run all tests, syntax/import checks, and acceptance scenarios against the candidate version with a temporary database/test bot.
2. Stop the production service, create a verified backup, and retain the previously deployed source/venv as a release artifact.
3. Install the new tested source and pinned dependencies; run `ops migrate` on the existing persistent database (it creates another pre-upgrade backup).
4. Start once and verify health, history, and group behavior. Do not run old and new pollers concurrently.
5. For code rollback, stop the service and restore the previous release only after checking schema compatibility. Migrations 2–3 are additive, but older code does not understand delivery reservations or newer controls. Inspect outstanding attempts before reverting so old code does not resend them.
6. If restoring the pre-upgrade database is necessary, follow the incident procedure and reconcile newer confirmations before restarting. Never erase new user data silently to make rollback easy.

SQLite foreign keys remain intentionally unenforced because the legacy `members` composite key is incompatible with the single-column reference in `payment_members`. Services and joins enforce group scoping. WAL is supported by backups but is not automatically enabled; the existing rollback-journal mode is retained with a five-second busy timeout and short transactions. Do not put the database on an unreliable network filesystem.
