import os
import json
import requests

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

GOOGLE_APPS_SCRIPT_URL = os.getenv(
    "GOOGLE_APPS_SCRIPT_URL"
)

GOOGLE_APPS_SCRIPT_SECRET = os.getenv(
    "GOOGLE_APPS_SCRIPT_SECRET"
)


# =========================================================
# ENVIRONMENT CHECK
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

if not GOOGLE_APPS_SCRIPT_URL:
    raise RuntimeError(
        "GOOGLE_APPS_SCRIPT_URL is not set"
    )

if not GOOGLE_APPS_SCRIPT_SECRET:
    raise RuntimeError(
        "GOOGLE_APPS_SCRIPT_SECRET is not set"
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

    return (
        "LINE AI Assistant is running",
        200
    )


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

The user may write in:
- English
- Thai
- mixed Thai and English

Analyze the user's message.

Classify it as:

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

1. type must be:
task
reminder
idea
note
meeting
conversation

2. task:
Create a short and clear description.
If there is no action, use null.

3. project:
Identify the work project or topic.
Otherwise use null.

4. deadline:
YYYY-MM-DD.
Otherwise null.

5. deadline_time:
HH:MM.
Otherwise null.

6. priority:
high
normal
low

7. person:
Important person involved.
Otherwise null.

8. summary:
Short useful summary.

9. Convert relative dates based
on today's date.

Examples:

tomorrow = next calendar day

Friday = next upcoming Friday

วันพรุ่งนี้ = tomorrow

วันศุกร์ = next upcoming Friday


USER MESSAGE:

{user_message}
"""


    # =====================================================
    # MODEL FALLBACK
    # =====================================================

    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.8-flash-lite"
    ]


    errors = []


    for model_name in models_to_try:

        try:

            print(
                f"Trying Gemini model: "
                f"{model_name}"
            )


            response = (
                gemini_client
                .models
                .generate_content(

                    model=model_name,

                    contents=prompt,

                    config=
                    types.GenerateContentConfig(
                        response_mime_type=
                        "application/json"
                    )
                )
            )


            if not response.text:

                raise RuntimeError(
                    "Gemini returned "
                    "an empty response"
                )


            # =================================================
            # TOKEN USAGE
            # =================================================

            usage = response.usage_metadata


            prompt_tokens = 0
            output_tokens = 0
            thinking_tokens = 0
            total_tokens = 0


            if usage:

                prompt_tokens = (
                    usage.prompt_token_count
                    or 0
                )

                output_tokens = (
                    usage.candidates_token_count
                    or 0
                )

                thinking_tokens = (
                    getattr(
                        usage,
                        "thoughts_token_count",
                        0
                    )
                    or 0
                )

                total_tokens = (
                    usage.total_token_count
                    or 0
                )


            result = json.loads(
                response.text
            )


            # =================================================
            # ADD TECHNICAL DATA
            # =================================================

            result["_model"] = (
                model_name
            )

            result["_prompt_tokens"] = (
                prompt_tokens
            )

            result["_output_tokens"] = (
                output_tokens
            )

            result["_thinking_tokens"] = (
                thinking_tokens
            )

            result["_total_tokens"] = (
                total_tokens
            )

            result["_fallback_used"] = (
                model_name
                != models_to_try[0]
            )


            print(
                "Gemini success:",
                model_name
            )


            return result


        except Exception as error:

            error_text = str(error)

            print(
                "Gemini model failed:",
                model_name,
                error_text
            )

            errors.append(
                model_name
                + ": "
                + error_text
            )


    raise RuntimeError(
        "All Gemini models failed:\n"
        + "\n".join(errors)
    )


# =========================================================
# SAVE TO GOOGLE SHEET
# =========================================================

def save_to_google_sheet(
    data,
    original_message
):

    payload = {

        "secret":
            GOOGLE_APPS_SCRIPT_SECRET,

        "type":
            data.get("type"),

        "task":
            data.get("task"),

        "project":
            data.get("project"),

        "deadline":
            data.get("deadline"),

        "priority":
            data.get(
                "priority",
                "normal"
            ),

        "status":
            "Open",

        "original_message":
            original_message
    }


    print(
        "Sending to Google Sheet..."
    )


    response = requests.post(

        GOOGLE_APPS_SCRIPT_URL,

        json=payload,

        timeout=20,

        allow_redirects=True
    )


    print(
        "Google status:",
        response.status_code
    )

    print(
        "Google response:",
        response.text
    )


    if response.status_code != 200:

        raise RuntimeError(
            "Google Apps Script HTTP "
            + str(response.status_code)
        )


    try:

        result = response.json()

    except Exception:

        raise RuntimeError(
            "Invalid Google response: "
            + response.text[:300]
        )


    if result.get("status") != "success":

        raise RuntimeError(
            result.get(
                "message",
                "Google Sheet save failed"
            )
        )


    return True


# =========================================================
# FORMAT LINE RESULT
# =========================================================

def format_result(
    data,
    saved_to_sheet=False
):

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


    model = data.get(
        "_model",
        "Unknown"
    )

    prompt_tokens = data.get(
        "_prompt_tokens",
        0
    )

    output_tokens = data.get(
        "_output_tokens",
        0
    )

    thinking_tokens = data.get(
        "_thinking_tokens",
        0
    )

    total_tokens = data.get(
        "_total_tokens",
        0
    )

    fallback_used = data.get(
        "_fallback_used",
        False
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
            f"📅 Deadline: "
            f"{deadline_text}"
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


    # =====================================================
    # SAVE STATUS
    # =====================================================

    lines.append("")


    if saved_to_sheet:

        lines.append(
            "💾 Saved to Google Sheet ✅"
        )

    elif message_type == "conversation":

        lines.append(
            "💬 Conversation not stored"
        )

    else:

        lines.append(
            "⚠️ Google Sheet save failed"
        )


    # =====================================================
    # AI STATUS
    # =====================================================

    lines.append("")

    lines.append(
        "──────────────"
    )

    lines.append(
        "⚙️ AI Status"
    )


    if fallback_used:

        lines.append(
            "🔄 Fallback model used"
        )

    else:

        lines.append(
            "✅ Primary model"
        )


    lines.append(
        f"🧠 Model: {model}"
    )


    lines.append(
        f"📥 Input: "
        f"{prompt_tokens} tokens"
    )


    lines.append(
        f"📤 Output: "
        f"{output_tokens} tokens"
    )


    if thinking_tokens > 0:

        lines.append(
            f"💭 Thinking: "
            f"{thinking_tokens} tokens"
        )


    lines.append(
        f"📊 Total: "
        f"{total_tokens} tokens"
    )


    return "\n".join(
        lines
    )


# =========================================================
# LINE TEXT MESSAGE
# =========================================================

@handler.add(
    MessageEvent,
    message=TextMessageContent
)
def handle_text_message(event):

    user_message = (
        event.message.text
    )


    print(
        "========== USER MESSAGE =========="
    )

    print(
        user_message
    )


    try:

        # =================================================
        # AI ANALYSIS
        # =================================================

        result = analyze_message(
            user_message
        )


        # =================================================
        # GOOGLE SHEET
        # =================================================

        saved_to_sheet = False


        types_to_save = [

            "task",

            "reminder",

            "meeting",

            "idea",

            "note"
        ]


        if result.get(
            "type"
        ) in types_to_save:

            try:

                save_to_google_sheet(
                    result,
                    user_message
                )

                saved_to_sheet = True


            except Exception as sheet_error:

                print(
                    "GOOGLE SHEET ERROR:"
                )

                print(
                    str(sheet_error)
                )


        # =================================================
        # FORMAT RESPONSE
        # =================================================

        reply_text = format_result(
            result,
            saved_to_sheet
        )


    except Exception as error:

        print(
            "========== AI ERROR =========="
        )

        print(
            str(error)
        )


        error_text = str(error)


        if len(error_text) > 800:

            error_text = (
                error_text[:800]
            )


        reply_text = (
            "⚠️ AI Assistant error\n\n"
            + error_text
        )


    # =====================================================
    # SEND TO LINE
    # =====================================================

    with ApiClient(
        configuration
    ) as api_client:

        line_api = MessagingApi(
            api_client
        )


        line_api.reply_message(

            ReplyMessageRequest(

                reply_token=
                event.reply_token,

                messages=[

                    TextMessage(
                        text=reply_text
                    )

                ]

            )

        )


# =========================================================
# START
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