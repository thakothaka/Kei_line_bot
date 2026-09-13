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


app = Flask(__name__)


# =========================
# ENVIRONMENT VARIABLES
# =========================

LINE_CHANNEL_ACCESS_TOKEN = os.getenv(
    "LINE_CHANNEL_ACCESS_TOKEN"
)

LINE_CHANNEL_SECRET = os.getenv(
    "LINE_CHANNEL_SECRET"
)

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY"
)

if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("Missing LINE_CHANNEL_ACCESS_TOKEN")

if not LINE_CHANNEL_SECRET:
    raise RuntimeError("Missing LINE_CHANNEL_SECRET")


# =========================
# LINE CONFIG
# =========================

configuration = Configuration(
    access_token=LINE_CHANNEL_ACCESS_TOKEN
)

handler = WebhookHandler(
    LINE_CHANNEL_SECRET
)


# =========================
# GEMINI CONFIG
# =========================

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY
)


# =========================
# WEB ROUTES
# =========================

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

    if not signature:
        abort(400)

    try:

        handler.handle(
            body,
            signature
        )

    except InvalidSignatureError:

        abort(400)

    return "OK", 200


# =========================
# AI FUNCTION
# =========================

def analyze_message(user_message):

    bangkok_time = datetime.now(
        ZoneInfo("Asia/Bangkok")
    )

    today = bangkok_time.strftime(
        "%Y-%m-%d"
    )

    weekday = bangkok_time.strftime(
        "%A"
    )

    prompt = f"""
You are a personal work assistant.

Current date in Thailand:
{today}

Today is:
{weekday}

Analyze the user's message.

User may write in:
- English
- Thai
- mixed Thai and English

Your job is to determine whether the message
contains a work task, reminder, idea, information,
meeting, or general conversation.

Extract these fields:

type:
- task
- reminder
- idea
- note
- meeting
- conversation

task:
Short clear description.

project:
Project or work topic if identifiable.
If unknown, use null.

deadline:
Use YYYY-MM-DD format.
If no deadline exists, use null.

deadline_time:
Use HH:MM 24-hour format.
If no time exists, use null.

priority:
- high
- normal
- low

person:
Important person involved.
If none, use null.

summary:
Short useful summary.

If user uses relative dates such as:
- tomorrow
- next Friday
- วันพรุ่งนี้
- วันศุกร์หน้า

calculate the real date based on the current date.

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

    result = json.loads(
        response.text
    )

    return result


# =========================
# FORMAT RESULT
# =========================

def format_result(data):

    type_value = data.get(
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

    lines.append("🤖 AI Assistant")
    lines.append("")

    lines.append(
        f"Type: {type_value}"
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


# =========================
# LINE MESSAGE HANDLER
# =========================

@handler.add(
    MessageEvent,
    message=TextMessageContent
)
def handle_text_message(event):

    user_message = event.message.text

    try:

        result = analyze_message(
            user_message
        )

        reply_text = format_result(
            result
        )

    except Exception as error:

        print(
            "Gemini error:",
            error
        )

        reply_text = (
            "⚠️ I received your message, "
            "but AI analysis failed.\n\n"
            "Please try again."
        )

    with ApiClient(
        configuration
    ) as api_client:

        line_api = MessagingApi(
            api_client
        )

        try:

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

        except Exception as error:

            print(
                "LINE reply error:",
                error
            )


# =========================
# RUN APP
# =========================

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