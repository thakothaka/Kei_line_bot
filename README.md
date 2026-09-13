# LINE AI Assistant — Step 6

This is the first connectivity test for a personal LINE OA AI assistant.

At this stage, the project only connects:

LINE OA -> Render -> LINE reply

No AI or Google integration is included yet.

## 1. GitHub

Upload these files to a GitHub repository.

Do not upload real LINE tokens.

## 2. Render

Create a Web Service connected to the GitHub repository.

Settings:

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Instance Type: Free

Add these environment variables in Render:

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_CHANNEL_SECRET`

## 3. Test Render

Open:

`https://YOUR-SERVICE.onrender.com/`

Expected:

`LINE AI Assistant is running`

## 4. LINE webhook

Set the webhook URL in LINE Developers to:

`https://YOUR-SERVICE.onrender.com/callback`

Click Verify.

Then enable `Use webhook`.

## 5. Test LINE

Send:

`Hello`

Expected response:

`AI Assistant is connected ✅`

`I received:`
`Hello`

## Important

Render Free Web Services can sleep when inactive. The first request after sleeping may be slower.

Do not use Render local storage for permanent files.
