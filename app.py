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

required_vars = {
    "LINE_CHANNEL_ACCESS_TOKEN":
        LINE_CHANNEL_ACCESS_TOKEN,

    "LINE_CHANNEL_SECRET":
        LINE_CHANNEL_SECRET,

    "GEMINI_API_KEY":
        GEMINI_API_KEY,

    "GOOGLE_APPS_SCRIPT_URL":
        GOOGLE_APPS_SCRIPT_URL,

    "GOOGLE_APPS_SCRIPT_SECRET":
        GOOGLE_APPS_SCRIPT_SECRET
}


for name, value in required_vars.items():

    if not value:

        raise RuntimeError(
            f"{name} is not set"
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
# WEB ROUTES
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

    current_date = (
        bangkok_time.strftime(
            "%Y-%m-%d"
        )
    )

    current_weekday = (
        bangkok_time.strftime(
            "%A"
        )
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

Classify it into exactly one type:

- task
- reminder
- idea
- note
- meeting
- conversation

Return JSON only.

Use exactly this structure:

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
Create a short and clear description.
If no action is required, use null.

3. project:
Identify project or work topic
if possible.
Otherwise null.

4. deadline:
Use YYYY-MM-DD.
Otherwise null.

5. deadline_time:
Use HH:MM in 24-hour format.
Otherwise null.

6. priority:
Use:
high
normal
low

7. person:
Important person involved.
Otherwise null.

8. summary:
Create a short useful summary.

9. Convert relative dates using
the current Thailand date.

Examples:

tomorrow = next calendar day

Friday = next upcoming Friday

วันพรุ่งนี้ = tomorrow

วันศุกร์ = next upcoming Friday

10. Do not invent a deadline if
the user does not mention one.

11. Do not classify greetings,
questions, or general chat as tasks.


USER MESSAGE:

{user_message}
"""


    # =====================================================
    # MODEL FALLBACK LIST
    # =====================================================
    #
    # Lighter models first.
    #
    # If a model is not available to your API project,
    # it will simply fail and move to the next model.
    # =====================================================

    models_to_try = [

        "gemini-3.1-flash-lite",

        "gemini-3.5-flash-lite",

        "gemini-3.5-flash",

        "gemini-3.6-flash",

        "gemini-3.7-flash",

        "gemini-3.8-flash",

        "gemini-2.5-flash-lite"
    ]


    errors = []


    # =====================================================
    # TRY EACH MODEL
    # =====================================================

    for model_index, model_name in enumerate(
        models_to_try
    ):

        try:

            attempt_number = (
                model_index + 1
            )


            print(
                "================================="
            )

            print(
                f"Gemini attempt "
                f"{attempt_number}"
            )

            print(
                f"Model: {model_name}"
            )

            print(
                "================================="
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
                        "application/json",

                        temperature=0.1

                    )
                )
            )


            # =================================================
            # EMPTY RESPONSE CHECK
            # =================================================

            if not response.text:

                raise RuntimeError(
                    "Gemini returned "
                    "an empty response"
                )


            # =================================================
            # TOKEN USAGE
            # =================================================

            usage = (
                response.usage_metadata
            )


            prompt_tokens = 0
            output_tokens = 0
            thinking_tokens = 0
            total_tokens = 0


            if usage:

                prompt_tokens = (
                    getattr(
                        usage,
                        "prompt_token_count",
                        0
                    )
                    or 0
                )


                output_tokens = (
                    getattr(
                        usage,
                        "candidates_token_count",
                        0
                    )
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
                    getattr(
                        usage,
                        "total_token_count",
                        0
                    )
                    or 0
                )


            # =================================================
            # PARSE JSON
            # =================================================

            print(
                "RAW GEMINI RESPONSE:"
            )

            print(
                response.text
            )


            result = json.loads(
                response.text
            )


            # =================================================
            # ADD INTERNAL DATA
            # =================================================

            result["_model"] = (
                model_name
            )


            result["_attempt"] = (
                attempt_number
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


            print(
                "================================="
            )

            print(
                "GEMINI SUCCESS"
            )

            print(
                f"Model: {model_name}"
            )

            print(
                f"Attempt: "
                f"{attempt_number}"
            )

            print(
                f"Total tokens: "
                f"{total_tokens}"
            )

            print(
                "================================="
            )


            return result


        # =====================================================
        # MODEL FAILED
        # =====================================================

        except Exception as error:

            error_text = str(error)


            print(
                "================================="
            )

            print(
                "MODEL FAILED"
            )

            print(
                f"Model: {model_name}"
            )

            print(
                f"Error: {error_text}"
            )

            print(
                "================================="
            )


            errors.append(
                {
                    "model":
                        model_name,

                    "error":
                        error_text
                }
            )


            # Automatically move
            # to next model

            continue


    # =====================================================
    # ALL MODELS FAILED
    # =====================================================

    error_summary = []


    for item in errors:

        short_error = (
            item["error"][:180]
        )

        error_summary.append(
            f"{item['model']}: "
            f"{short_error}"
        )


    raise RuntimeError(

        "All Gemini models failed:\n"
        +
        "\n".join(
            error_summary
        )

    )


# =========================================================
# GOOGLE SHEET
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

        "deadline_time":
            data.get(
                "deadline_time"
            ),

        "priority":
            data.get(
                "priority",
                "normal"
            ),

        "person":
            data.get("person"),

        "summary":
            data.get("summary"),

        "status":
            "Open",

        "original_message":
            original_message

    }


    print(
        "Sending data to Google Apps Script..."
    )


    response = requests.post(

        GOOGLE_APPS_SCRIPT_URL,

        json=payload,

        timeout=30,

        allow_redirects=True
    )


    print(
        "Google HTTP status:",
        response.status_code
    )


    print(
        "Google response:",
        response.text[:500]
    )


    if response.status_code != 200:

        raise RuntimeError(

            "Google Apps Script returned HTTP "
            +
            str(
                response.status_code
            )

        )


    try:

        result = (
            response.json()
        )


    except Exception:

        raise RuntimeError(

            "Google Apps Script "
            "returned invalid JSON: "
            +
            response.text[:300]

        )


    if (
        result.get("status")
        !=
        "success"
    ):

        raise RuntimeError(

            result.get(
                "message",
                "Google Sheet save failed"
            )

        )


    return True


# =========================================================
# FORMAT LINE RESPONSE
# =========================================================

def format_result(
    data,
    saved_to_sheet=False,
    sheet_error=None
):

    message_type = (
        data.get(
            "type",
            "conversation"
        )
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


    # =====================================================
    # AI TECHNICAL INFO
    # =====================================================

    model = data.get(
        "_model",
        "Unknown"
    )


    attempt = data.get(
        "_attempt",
        1
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


    # =====================================================
    # BUILD MESSAGE
    # =====================================================

    lines = []


    lines.append(
        "🤖 AI Assistant"
    )


    lines.append("")


    lines.append(
        f"Type: {message_type}"
    )


    # =====================================================
    # TASK
    # =====================================================

    if task:

        lines.append(
            f"📌 Task: {task}"
        )


    # =====================================================
    # PROJECT
    # =====================================================

    if project:

        lines.append(
            f"📁 Project: {project}"
        )


    # =====================================================
    # DEADLINE
    # =====================================================

    if deadline:

        deadline_text = (
            deadline
        )


        if deadline_time:

            deadline_text += (
                " "
                +
                deadline_time
            )


        lines.append(
            f"📅 Deadline: "
            f"{deadline_text}"
        )


    # =====================================================
    # PRIORITY
    # =====================================================

    if priority:

        lines.append(
            f"⭐ Priority: {priority}"
        )


    # =====================================================
    # PERSON
    # =====================================================

    if person:

        lines.append(
            f"👤 Person: {person}"
        )


    # =====================================================
    # SUMMARY
    # =====================================================

    if summary:

        lines.append("")

        lines.append(
            f"Summary: {summary}"
        )


    # =====================================================
    # DATABASE STATUS
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


        if sheet_error:

            lines.append(
                f"Reason: "
                f"{sheet_error[:150]}"
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


    if attempt == 1:

        lines.append(
            "✅ Primary model"
        )

    else:

        lines.append(
            f"🔄 Fallback #{attempt - 1}"
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
# LINE TEXT HANDLER
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
        "================================="
    )

    print(
        "USER MESSAGE"
    )

    print(
        user_message
    )

    print(
        "================================="
    )


    try:

        # =================================================
        # ANALYZE WITH GEMINI
        # =================================================

        result = analyze_message(
            user_message
        )


        # =================================================
        # DECIDE WHETHER TO STORE
        # =================================================

        saved_to_sheet = False

        sheet_error_text = None


        types_to_save = [

            "task",

            "reminder",

            "meeting",

            "idea",

            "note"

        ]


        if (
            result.get("type")
            in
            types_to_save
        ):

            try:

                save_to_google_sheet(
                    result,
                    user_message
                )


                saved_to_sheet = True


            except Exception as sheet_error:

                sheet_error_text = (
                    str(sheet_error)
                )


                print(
                    "================================="
                )

                print(
                    "GOOGLE SHEET ERROR"
                )

                print(
                    sheet_error_text
                )

                print(
                    "================================="
                )


        # =================================================
        # FORMAT RESPONSE
        # =================================================

        reply_text = format_result(

            result,

            saved_to_sheet,

            sheet_error_text

        )


    # =====================================================
    # GENERAL ERROR
    # =====================================================

    except Exception as error:

        print(
            "================================="
        )

        print(
            "AI ASSISTANT ERROR"
        )

        print(
            str(error)
        )

        print(
            "================================="
        )


        error_text = str(
            error
        )


        if (
            len(error_text)
            >
            1000
        ):

            error_text = (
                error_text[:1000]
            )


        reply_text = (

            "⚠️ AI Assistant error\n\n"
            +
            error_text

        )


    # =====================================================
    # SEND MESSAGE TO LINE
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
# START APPLICATION
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