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
# AI FUNCTION
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

Classify it as one of:

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

1. type:
task, reminder, idea, note,
meeting, conversation

2. task:
Short and clear.
If no task, use null.

3. project:
Identify project or work topic.
If unknown, use null.

4. deadline:
YYYY-MM-DD.
If no deadline, use null.

5. deadline_time:
HH:MM.
If no time, use null.

6. priority:
high, normal, low.

7. person:
Important person involved.
Otherwise null.

8. summary:
Short useful summary.

9. Convert relative dates using
the current date.

Examples:

tomorrow = next calendar day

Friday = next upcoming Friday

วันพรุ่งนี้ = tomorrow

วันศุกร์ = next upcoming Friday


USER MESSAGE:

{user_message}
"""


    # Model priority
    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.8-flash-lite"
    ]


    errors = []


    for model_name in models_to_try:

        try:

            print(
                f"Trying model: {model_name}"
            )


            response = (
                gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type=
                        "application/json"
                    )
                )
            )


            if not response.text:

                raise RuntimeError(
                    "Gemini returned empty response"
                )


            # =============================================
            # TOKEN USAGE
            # =============================================

            usage = response.usage_metadata


            prompt_tokens = 0
            output_tokens = 0
            total_tokens = 0
            thinking_tokens = 0


            if usage:

                prompt_tokens = (
                    usage.prompt_token_count or 0
                )

                output_tokens = (
                    usage.candidates_token_count or 0
                )

                total_tokens = (
                    usage.total_token_count or 0
                )

                thinking_tokens = (
                    getattr(
                        usage,
                        "thoughts_token_count",
                        0
                    )
                    or 0
                )


            print(
                "========== GEMINI SUCCESS =========="
            )

            print(
                "Model:",
                model_name
            )

            print(
                "Input tokens:",
                prompt_tokens
            )

            print(
                "Output tokens:",
                output_tokens
            )

            print(
                "Thinking tokens:",
                thinking_tokens
            )

            print(
                "Total tokens:",
                total_tokens
            )

            print(
                "===================================="
            )


            result = json.loads(
                response.text
            )


            # Add technical information
            # to our result

            result["_model"] = model_name

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
                model_name != models_to_try[0]
            )


            return result


        except Exception as error:

            error_string = str(error)

            print(
                "========== MODEL FAILED =========="
            )

            print(
                model_name
            )

            print(
                type(error).__name__
            )

            print(
                error_string
            )

            print(
                "=================================="
            )


            errors.append(
                f"{model_name}: "
                + error_string
            )


            # Continue to next model
            continue


    # If every model fails

    raise RuntimeError(
        "All Gemini models failed:\n"
        + "\n".join(errors)
    )


# =========================================================
# FORMAT AI RESULT
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


    # Technical usage

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


    # =============================================
    # AI STATUS
    # =============================================

    lines.append("")
    lines.append(
        "──────────────"
    )

    lines.append(
        "⚙️ AI Status"
    )


    if fallback_used:

        lines.append(
            "🔄 Fallback used"
        )

    else:

        lines.append(
            "✅ Primary model"
        )


    lines.append(
        f"🧠 Model: {model}"
    )


    lines.append(
        f"📥 Input: {prompt_tokens} tokens"
    )


    lines.append(
        f"📤 Output: {output_tokens} tokens"
    )


    if thinking_tokens > 0:

        lines.append(
            f"💭 Thinking: "
            f"{thinking_tokens} tokens"
        )


    lines.append(
        f"📊 Total: {total_tokens} tokens"
    )


    return "\n".join(
        lines
    )


# =========================================================
# LINE MESSAGE HANDLER
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
        "========== USER =========="
    )

    print(
        user_message
    )

    print(
        "=========================="
    )


    try:

        result = analyze_message(
            user_message
        )

        reply_text = format_result(
            result
        )


    except Exception as error:

        print(
            "========== AI ERROR =========="
        )

        print(
            type(error).__name__
        )

        print(
            str(error)
        )

        print(
            "=============================="
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


    # =============================================
    # SEND REPLY TO LINE
    # =============================================

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
# START APP
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