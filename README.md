# BongLuy — Monthly Payment Reminder Bot

A Telegram bot for managing recurring monthly payments across multiple Telegram groups.

BongLuy lets members register for payment tracking, lets admins create recurring monthly payments and assign members, and automatically reminds unpaid members until everyone has paid.

## Features

- Multi-group support
- Member registration with `/join`
- Group onboarding with a **Join Payment Tracking** button
- Private admin dashboard via `/start`
- Recurring monthly payments
- Assign/unassign members per payment
- Monthly payment-status tracking
- `✅ I've Paid` action
- Daily reminders until everyone has paid
- Username mentions with Telegram user-link fallback
- Duplicate reminder protection
- Payment editing
- Disable/reactivate payments
- Payment status/history tracking
- SQLite database
- APScheduler background reminder checks

## Tech Stack

- Python 3.12
- aiogram 3
- APScheduler
- SQLite
- python-dotenv

## Requirements

Install:

- Python 3.12+
- Git
- A Telegram bot token from BotFather

Optional but recommended:

- GitHub CLI (`gh`)
- A VPS or cloud host for 24/7 deployment

## Project Structure

```text
monthly-payment-reminder/
├── constants/
├── database/
├── deploy/
├── handlers/
├── keyboards/
├── models/
├── modules/
├── ops/
├── scheduler/
├── services/
├── tests/
├── utils/
├── .env
├── .env.example
├── .gitignore
├── app.py
├── config.py
├── DEPLOYMENT.md
├── IMPLEMENTATION_NOTES.md
├── pytest.ini
├── README.md
├── requirements-dev.txt
└── requirements.txt
```

## 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/monthly-payment-reminder.git
cd monthly-payment-reminder
```

If you already have the project locally, skip this step.

## 2. Create a Virtual Environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

For development/testing dependencies:

```bash
pip install -r requirements-dev.txt
```

## 4. Configure Environment Variables

Create `.env` from the example file:

```bash
cp .env.example .env
```

Example:

```env
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
APP_TIMEZONE=Asia/Phnom_Penh
REMINDER_CHECK_SECONDS=60
DATABASE_PATH=reminder.db
REMINDER_POLICY=daily_until_paid
LOG_LEVEL=INFO
```

Use `.env.example` as the source of truth if the project gains more environment variables later.

## 5. Run the Bot

```bash
python3 app.py
```

On startup, the bot should initialize the database, run migrations, start the reminder scheduler, and begin Telegram polling.

Stop it with:

```text
Ctrl + C
```

## Telegram Setup

### Create the Bot

1. Open Telegram.
2. Search for `@BotFather`.
3. Run `/newbot`.
4. Follow the instructions.
5. Copy the bot token.
6. Put it in `.env` as `BOT_TOKEN`.

### Add BongLuy to a Group

1. Add the bot to your Telegram group.
2. Give it the permissions required by your setup.
3. A member runs:

```text
/join
```

The first onboarding flow should post something like:

```text
👋 This group uses BongLuy for payment tracking.

Tap below to register so admins can assign you to payments.

[✅ Join Payment Tracking]
```

Other members can tap the button to register.

### Admin Dashboard

Open a private chat with the bot and run:

```text
/start
```

The bot will show the groups you can manage.

## Member Registration

Members can register directly inside a group:

```text
/join
```

A successful registration looks like:

```text
✅ Jonathan joined payment tracking.
```

A member is registered separately for each group.

## Payment Flow

Typical admin flow:

```text
/start
→ Select group
→ Add Payment
→ Enter payment name
→ Enter amount
→ Select currency
→ Set due day
→ Set reminder time
→ Assign members
```

Example:

```text
Internet
$25 USD
Due: every 15th
Reminder: 09:00
```

## Reminder Behavior

The scheduler periodically checks active payments.

For an eligible payment, BongLuy can:

- initialize the current month's payment statuses
- find assigned members
- mention only unpaid members
- send the reminder to the correct Telegram group
- provide a `✅ I've Paid` button
- mark the clicking member as paid
- continue daily reminders according to policy
- stop reminding once everyone assigned to that payment has paid

Historical status rows remain available across monthly cycles.

## SQLite Database

Default configuration:

```env
DATABASE_PATH=reminder.db
```

The database stores groups, members, payments, assignments, monthly statuses, migration state, and reminder-dispatch data.

### Important

Do **not** delete the production database unless you intentionally want to erase saved bot data.

For cloud deployment, SQLite must be stored on **persistent storage**.

Example:

```env
DATABASE_PATH=/data/reminder.db
```

where `/data` is a persistent volume mounted by your hosting provider.

If SQLite is stored only on an ephemeral filesystem, the database may disappear after a redeploy or restart.

## Database Migrations

Migrations run automatically during application startup.

Normally you only need:

```bash
python3 app.py
```

Back up important production data before making destructive schema changes.

## Testing

Run the test suite:

```bash
pytest
```

Verbose output:

```bash
pytest -v
```

Syntax check:

```bash
python3 -m compileall .
```

## Git Setup

Make sure `.gitignore` includes sensitive/generated files:

```gitignore
.env
.venv/
__pycache__/
*.pyc
reminder.db
reminder.db-*
backups/
.pytest_cache/
```

Never commit your Telegram bot token.

### First Commit

```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
```

## Create the GitHub Repository with GitHub CLI

Install GitHub CLI on macOS:

```bash
brew install gh
```

Login:

```bash
gh auth login
```

Then create a private repository and push the current project:

```bash
gh repo create monthly-payment-reminder --private --source=. --remote=origin --push
```

## Normal Git Push Workflow

After making changes:

```bash
git status
git add .
git commit -m "describe your changes"
git push
```

Example:

```bash
git add .
git commit -m "finish onboarding and member management"
git push
```

## Deployment

BongLuy is a long-running Python process.

A suitable production host needs:

- Python runtime
- always-on/background process support
- persistent storage for SQLite
- environment variable support
- automatic restart after crashes/reboots

Possible hosts:

- Railway
- Render
- DigitalOcean
- Hetzner VPS
- AWS EC2
- another Linux VPS

### Production Environment Example

```env
BOT_TOKEN=YOUR_PRODUCTION_TOKEN
APP_TIMEZONE=Asia/Phnom_Penh
REMINDER_CHECK_SECONDS=60
DATABASE_PATH=/data/reminder.db
REMINDER_POLICY=daily_until_paid
LOG_LEVEL=INFO
```

Do not commit production secrets to Git.

## VPS Example

```bash
git clone https://github.com/YOUR_USERNAME/monthly-payment-reminder.git
cd monthly-payment-reminder

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`, then test:

```bash
python3 app.py
```

For production, run the bot through a restart-capable service such as `systemd`, Docker, or another process manager instead of keeping it attached to an SSH terminal.

## Security Notes

Never publish:

- `.env`
- `BOT_TOKEN`
- production database files
- database backups containing group/member data
- secret API keys

If a bot token is accidentally pushed to GitHub, revoke it immediately through BotFather and generate a new token.

## Useful Commands

Activate environment:

```bash
source .venv/bin/activate
```

Run bot:

```bash
python3 app.py
```

Run tests:

```bash
pytest
```

Check Git:

```bash
git status
```

Pull latest changes:

```bash
git pull
```

Push changes:

```bash
git add .
git commit -m "update bot"
git push
```

Exit virtual environment:

```bash
deactivate
```

## Production Checklist

Before using BongLuy with real groups:

- Confirm `.env` is ignored by Git.
- Confirm `reminder.db` is ignored by Git.
- Run the full test suite.
- Test `/join` in a fresh Telegram group.
- Test the **Join Payment Tracking** button.
- Test admin group discovery through `/start`.
- Create a test payment.
- Assign multiple members.
- Test reminder behavior.
- Test the `✅ I've Paid` action.
- Confirm duplicate reminders are prevented.
- Test disable/reactivate.
- Test member management.
- Confirm production SQLite uses persistent storage.
- Set up backups.
- Confirm the bot restarts automatically after a server reboot.

## License

Private project unless you decide to publish it under a specific license.
