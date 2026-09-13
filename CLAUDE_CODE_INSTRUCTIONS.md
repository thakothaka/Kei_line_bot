# Claude Code Instructions — LINE AI Assistant Step 6

## Goal

Build and deploy the first working version of a personal LINE OA assistant on Render.

For this step, DO NOT add Gemini, Google Drive, Google Sheets, or Google Calendar yet.

The only goal is:

1. LINE sends a webhook event to Render.
2. Render validates the LINE webhook signature.
3. The bot replies to a text message.
4. LINE webhook verification returns HTTP 200.
5. The deployment must stay compatible with Render Free Web Service.

## Architecture

LINE OA
  -> HTTPS webhook
Render Web Service
  -> Flask app
  -> LINE Messaging API reply

## Required environment variables

Do not hard-code secrets.

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_CHANNEL_SECRET`

These must be configured in Render Environment Variables.

Never commit real tokens or secrets to GitHub.

## Expected endpoints

### GET /

Returns:

`LINE AI Assistant is running`

HTTP status: 200

Used only as a simple health check.

### POST /callback

Receives LINE webhook events.

Requirements:
- Read `X-Line-Signature`
- Validate the signature using `LINE_CHANNEL_SECRET`
- Process LINE text-message events
- Reply using `LINE_CHANNEL_ACCESS_TOKEN`
- Return `OK` with HTTP 200 when successful
- Return HTTP 400 for an invalid or missing signature

## Expected LINE behavior

If the user sends:

`Hello`

the bot should reply:

`AI Assistant is connected ✅`

followed by:

`I received:`
`Hello`

## Render settings

Use a Render Web Service.

- Runtime / Language: Python
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Instance type: Free only

Do not add:
- Render Postgres
- Persistent disk
- Background workers
- Cron jobs
- Paid instance types
- Any service that can create avoidable charges

## Cost constraint

This project is intended to remain within free tiers.

Do not change the architecture to a paid Render service without explicit approval.

Do not store files on Render's local filesystem as permanent storage. Later versions will use Google Drive.

## Files

- `app.py` — Flask webhook server
- `requirements.txt` — Python dependencies
- `.env.example` — variable names only
- `.gitignore` — prevents secret files from being committed

## What Claude Code may do

Claude Code may:
- review the code
- fix compatibility issues
- improve error handling
- add logging
- create or update a README
- help prepare GitHub deployment

Claude Code should NOT:
- replace Render with another platform
- add paid infrastructure
- add AI features yet
- add database infrastructure yet
- put credentials in source code

## Test checklist

Before moving to Step 7, verify:

1. `GET /` returns HTTP 200.
2. Render deployment succeeds.
3. LINE webhook URL is:
   `https://<render-service-name>.onrender.com/callback`
4. LINE Developers -> Webhook -> Verify shows success.
5. `Use webhook` is ON.
6. Sending `Hello` in LINE receives the expected reply.

Once all six checks pass, Step 6 is complete.
