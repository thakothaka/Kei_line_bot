# Kei AI Assistant V8 Setup

This version adds:

- uncertain-result confirmation
- duplicate detection
- task IDs
- LINE task commands
- automatic Calendar reminders
- project recognition from a `Projects` tab
- daily LINE brief
- Google Drive evidence links
- PDF support
- daily AI usage counters and safety caps

## 1) Files to deploy

Render / GitHub:
- `app.py`
- `requirements.txt`

Google Apps Script:
- replace your current script with `Code.gs`

## 2) Render environment variables

Keep your current variables:

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_CHANNEL_SECRET`
- `GEMINI_API_KEY`
- `GOOGLE_APPS_SCRIPT_URL`
- `GOOGLE_APPS_SCRIPT_SECRET`

Optional safety settings:

- `GEMINI_MODELS=gemini-3.1-flash-lite,gemini-2.5-flash-lite`
- `AI_DAILY_REQUEST_LIMIT=60`
- `AI_DAILY_TOKEN_LIMIT=120000`
- `CONFIDENCE_THRESHOLD=0.85`
- `MAX_INLINE_FILE_BYTES=8388608`

The safety counters are your own protection, not Google's official remaining quota.

## 3) Apps Script Script Properties

Project Settings -> Script Properties:

- `API_SECRET` = same value as `GOOGLE_APPS_SCRIPT_SECRET` in Render

For the Daily Brief also add:

- `LINE_CHANNEL_ACCESS_TOKEN` = your LINE Messaging API channel access token

Do not place these values directly in source code.

## 4) Apps Script authorization

Run manually once:

- `authorizeAllServices`
- `testDriveWrite`

Approve Sheets, Calendar and Drive permissions if Google asks.

Then deploy a **new Web App version**:

- Execute as: Me
- Who has access: Anyone

Keep the `/exec` URL in Render.

## 5) Sheet tabs

The Apps Script automatically creates or extends these tabs:

### Tasks
Existing columns A:O are preserved. V8 adds:

- P `Task ID`
- Q `Confidence`
- R `Duplicate Key`
- S `Source File Name`
- T `Updated`

### Projects
Add your project vocabulary here:

| Project | Keywords | Active |
|---|---|---|
| Newsletter | newsletter, management talk | TRUE |
| Manager Seminar | seminar, hotel, agenda | TRUE |
| Visa Process | visa, health check, ministry of labor | TRUE |

The AI will use these exact project names when keywords match.

### Usage
Automatically records bot AI usage per request.

### Pending
Stores items waiting for your confirmation. Do not edit this manually unless troubleshooting.

## 6) Confirmation behavior

The bot asks for confirmation when:

- AI confidence is below the configured threshold
- a date/year was inferred
- AI flags ambiguity
- more than 10 items are detected
- a possible duplicate exists

Commands:

- `save all`
- `save all force`
- `cancel`
- `edit 2 deadline 2026-09-20`
- `edit 2 time 14:00`
- `edit 2 task New task name`
- `edit 2 priority high`

`save all` skips detected duplicates. `save all force` saves them anyway.

## 7) Work-management commands

- `today`
- `this week`
- `overdue`
- `show project Manager Seminar`
- `done T-20260914-001`
- `done Visa Application`
- `delete last`
- `delete last note`
- `change deadline T-20260914-001 to 2026-09-20`
- `change deadline Visa Application to 2026-09-20 14:00`
- `usage`
- `projects`
- `help`

## 8) Calendar reminders

Automatically applied:

- meeting: 1 day before + 1 hour before
- high-priority task/reminder: 3 days before + 1 day before
- normal/low task/reminder: 1 day before

When a task is marked `done`, its Calendar reminders are removed.
When its deadline changes, the old Calendar event is replaced.
When `delete last` removes an item, its Calendar event is deleted too.

## 9) Daily Brief

Apps Script can push a brief to LINE every morning.

Before enabling it:

1. Add `LINE_CHANNEL_ACCESS_TOKEN` to Apps Script Script Properties.
2. Send at least one normal message to your LINE bot after V8 is deployed. This lets the script learn your LINE user ID.
3. In Apps Script Project Settings, set the timezone to **Asia/Bangkok / GMT+7**.
4. Run `testDailyBrief` once.
5. If it works, run `createDailyBriefTrigger` once.

The brief reports:

- overdue count
- due today count
- next 7 days count
- today's task list

Important: LINE push messages count against your LINE OA outbound-message allowance. One brief per day is usually light usage, but keep an eye on your free-plan quota.

## 10) Image and PDF behavior

### Images
- downloaded from LINE
- analyzed by Gemini
- one source image saved to your selected Drive folder
- all extracted items point to the same Drive source file

### PDFs
- PDF files sent through LINE are analyzed
- the original PDF is saved to Drive
- extracted tasks/deadlines are saved separately

The code uses a conservative default 8 MB inline file limit. You can change it with `MAX_INLINE_FILE_BYTES` in Render.

## 11) Suggested tests

### Duplicate test
Send the same screenshot twice.
Expected on the second send: confirmation plus a duplicate warning.

### Uncertain-date test
Send an image saying:

`Submit report on 24 Sep`

with no year. Expected: confirmation because the year was inferred.

### Task commands

1. Send: `Prepare monthly report by Friday`
2. Send: `today`
3. Send: `this week`
4. Send: `done <Task ID>`
5. Send: `overdue`

### PDF test
Send a small PDF agenda containing several deadlines.
Expected: multiple extracted items plus Drive/Sheet/Calendar results.

