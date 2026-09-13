import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

from google import genai
from google.genai import types


# =========================================================
# APP
# =========================================================

app = Flask(__name__)


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

LINE_CHANNEL_ACCESS_TOKEN = os.getenv(
    "LINE_CHANNEL_ACCESS_TOKEN"
)

LINE_CHANNEL_SECRET = os.getenv(
    "LINE_CHANNEL_SECRET"
)

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY"
)


# =========================================================
# BASIC ENV CHECK
# =========================================================

if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError(
        "LINE_CHANNEL_ACCESS_TOKEN is not set"
    )

if not LINE_CHANNEL_SECRET:
    raise RuntimeError(
        "LINE_CHANNEL_SECRET is not set"
    )

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not set"
    )


# =========================================================
# LINE CONFIG
# =========================================================

configuration = Configuration(
    access_token=LINE_CHANNEL_ACCESS_TOKEN
)

handler = WebhookHandler(
    LINE_CHANNEL_SECRET
)


# =========================================================
# GEMINI CONFIG
# =========================================================

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY
)


# =========================================================
# ROUTES
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return "LINE AI Assistant is running", 200


@app.route("/callback", methods=["POST"])
def callback():

    signature = request.headers.get(
        "X-Line-Signature"
    )

    body = request.get_data(
        as_text=True
    )

    try:
        handler.handle(
            body,
            signature
        )

    except InvalidSignatureError:
        abort(400)

    return "OK", 200


# =========================================================
# GEMINI ANALYSIS
# =========================================================

def analyze_message(user_message):

    bangkok_time = datetime.now(
        ZoneInfo("Asia/Bangkok")
    )

    current_date = bangkok_time.strftime(
        "%Y-%m-%d"
    )

    current_weekday = bangkok_time.strftime(
        "%A"
    )

    prompt = f"""
You are a personal work assistant.

Current date in Thailand:
{current_date}

Today is:
{current_weekday}

The user may write in English, Thai,
or mixed Thai and English.

Analyze the user's message.

Classify it into one of these types:

- task
- reminder
- idea
- note
- meeting
- conversation

Return JSON only.

Use exactly these fields:

{{
  "type": "task",
  "task": "short task description",
  "project": null,
  "deadline": null,
  "deadline_time": null,
  "priority": "normal",
  "person": null,
  "summary": "short summary"
}}

Rules:

1. type must be one of:
   task
   reminder
   idea
   note
   meeting
   conversation

2. task:
   Make it short and clear.
   If there is no task, use null.

3. project:
   Identify the project or work topic
   when possible.
   Otherwise use null.

4. deadline:
   Use YYYY-MM-DD.
   If there is no deadline, use null.

5. deadline_time:
   Use HH:MM in 24-hour format.
   If there is no time, use null.

6. priority:
   Use:
   high
   normal
   low

7. person:
   Important person involved.
   Otherwise use null.

8. summary:
   Short useful summary.

9. Convert relative dates based on today's date.

Examples:

"tomorrow"
means the next calendar day.

"Friday"
means the next upcoming Friday.

"วันพรุ่งนี้"
means tomorrow.

"วันศุกร์"
means the next upcoming Friday.

User message:

{user_message}
"""

    response = gemini_client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    if not response.text:
        raise RuntimeError(
            "Gemini returned an empty response"
        )

    print("========== GEMINI RAW ==========")
    print(response.text)
    print("================================")

    result = json.loads(
        response.text
    )

    return result


# =========================================================
# FORMAT RESULT
# =========================================================

def format_result(data):

    message_type = data.get(
        "type",
        "conversation"
    )

    task = data.get(
        "task"
    )

    project = data.get(
        "project"
    )

    deadline = data.get(
        "deadline"
    )

    deadline_time = data.get(
        "deadline_time"
    )

    priority = data.get(
        "priority",
        "normal"
    )

    person = data.get(
        "person"
    )

    summary = data.get(
        "summary"
    )

    lines = []

    lines.append(
        "🤖 AI Assistant"
    )

    lines.append("")

    lines.append(
        f"Type: {message_type}"
    )

    if task:
        lines.append(
            f"📌 Task: {task}"
        )

    if project:
        lines.append(
            f"📁 Project: {project}"
        )

    if deadline:

        deadline_text = deadline

        if deadline_time:
            deadline_text += (
                f" {deadline_time}"
            )

        lines.append(
            f"📅 Deadline: {deadline_text}"
        )

    if priority:
        lines.append(
            f"⭐ Priority: {priority}"
        )

    if person:
        lines.append(
            f"👤 Person: {person}"
        )

    if summary:
        lines.append("")
        lines.append(
            f"Summary: {summary}"
        )

    return "\n".join(lines)


# =========================================================
# LINE MESSAGE HANDLER
# =========================================================

@handler.add(
    MessageEvent,
    message=TextMessageContent
)
def handle_text_message(event):

    user_message = event.message.text

    print("========== USER MESSAGE ==========")
    print(user_message)
    print("==================================")

    try:

        result = analyze_message(
            user_message
        )

        reply_text = format_result(
            result
        )

    except Exception as error:

        print(
            "========== GEMINI ERROR =========="
        )

        print(
            type(error).__name__
        )

        print(
            str(error)
        )

        print(
            "=================================="
        )

        error_text = str(error)

        if len(error_text) > 700:
            error_text = error_text[:700]

        reply_text = (
            "⚠️ Gemini error\n\n"
            + type(error).__name__
            + "\n\n"
            + error_text
        )

    with ApiClient(
        configuration
    ) as api_client:

        line_api = MessagingApi(
            api_client
        )

        line_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                        text=reply_text
                    )
                ]
            )
        )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )