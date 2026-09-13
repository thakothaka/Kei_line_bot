import os
import json
import base64
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
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage
)

from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent
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


required_vars = {
    "LINE_CHANNEL_ACCESS_TOKEN": LINE_CHANNEL_ACCESS_TOKEN,
    "LINE_CHANNEL_SECRET": LINE_CHANNEL_SECRET,
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "GOOGLE_APPS_SCRIPT_URL": GOOGLE_APPS_SCRIPT_URL,
    "GOOGLE_APPS_SCRIPT_SECRET": GOOGLE_APPS_SCRIPT_SECRET
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
# PROMPT
# =========================================================

def build_prompt():

    bangkok_time = datetime.now(
        ZoneInfo("Asia/Bangkok")
    )

    current_date = bangkok_time.strftime(
        "%Y-%m-%d"
    )

    current_weekday = bangkok_time.strftime(
        "%A"
    )

    return f"""
You are a personal work assistant.

Current date in Thailand:
{current_date}

Today is:
{current_weekday}

The user may provide:
- English
- Thai
- mixed Thai and English
- screenshots
- photos
- meeting notes
- email screenshots
- documents shown in images

Analyze the content.

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
Short and clear.
If there is no action, use null.

3. project:
Identify project or work topic.
Otherwise null.

4. deadline:
Use YYYY-MM-DD.
Otherwise null.

5. deadline_time:
Use HH:MM in 24-hour format.
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

9. Convert relative dates using
the current Thailand date.

10. Do not invent a deadline.

11. If an image contains multiple dates,
choose the deadline most relevant
to the action.

12. If content is general information,
use note.

13. If casual chat only,
use conversation.
"""


# =========================================================
# GEMINI FALLBACK
# =========================================================

def call_gemini(contents):

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

    for model_index, model_name in enumerate(
        models_to_try
    ):

        try:

            attempt_number = model_index + 1

            print(
                f"Trying Gemini model: {model_name}"
            )

            response = (
                gemini_client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1
                    )
                )
            )

            if not response.text:
                raise RuntimeError(
                    "Gemini returned empty response"
                )

            usage = response.usage_metadata

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

            result = json.loads(
                response.text
            )

            result["_model"] = model_name
            result["_attempt"] = attempt_number
            result["_prompt_tokens"] = prompt_tokens
            result["_output_tokens"] = output_tokens
            result["_thinking_tokens"] = thinking_tokens
            result["_total_tokens"] = total_tokens

            return result

        except Exception as error:

            error_text = str(error)

            print(
                "Gemini model failed:",
                model_name,
                error_text
            )

            errors.append(
                f"{model_name}: {error_text[:200]}"
            )

            continue

    raise RuntimeError(
        "All Gemini models failed:\n"
        + "\n".join(errors)
    )


# =========================================================
# ANALYZE TEXT
# =========================================================

def analyze_text(user_message):

    prompt = build_prompt()

    full_prompt = (
        prompt
        + "\n\nUSER MESSAGE:\n"
        + user_message
    )

    return call_gemini(
        full_prompt
    )


# =========================================================
# ANALYZE IMAGE
# =========================================================

def analyze_image(image_bytes):

    prompt = build_prompt()

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type="image/jpeg"
    )

    contents = [
        prompt,
        image_part
    ]

    return call_gemini(
        contents
    )


# =========================================================
# SAVE TO GOOGLE
# =========================================================

def save_to_google(
    data,
    original_message,
    image_bytes=None
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
            data.get("deadline_time"),

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


    # =====================================================
    # IMAGE TO BASE64
    # =====================================================

    if image_bytes:

        image_base64 = (
            base64.b64encode(
                image_bytes
            )
            .decode("utf-8")
        )

        payload["image_base64"] = (
            image_base64
        )

        payload["image_mime_type"] = (
            "image/jpeg"
        )


    response = requests.post(
        GOOGLE_APPS_SCRIPT_URL,
        json=payload,
        timeout=60,
        allow_redirects=True
    )


    print(
        "Google status:",
        response.status_code
    )

    print(
        "Google response:",
        response.text[:1000]
    )


    if response.status_code != 200:

        raise RuntimeError(
            "Google Apps Script HTTP "
            + str(response.status_code)
        )


    result = response.json()


    if result.get("status") != "success":

        raise RuntimeError(
            result.get(
                "message",
                "Google save failed"
            )
        )


    return result


# =========================================================
# SHOULD SAVE
# =========================================================

def should_save(result):

    return result.get(
        "type"
    ) in [
        "task",
        "reminder",
        "meeting",
        "idea",
        "note"
    ]


# =========================================================
# FORMAT RESULT
# =========================================================

def format_result(
    data,
    google_result=None,
    save_error=None
):

    message_type = data.get(
        "type",
        "conversation"
    )

    task = data.get("task")
    project = data.get("project")
    deadline = data.get("deadline")
    deadline_time = data.get("deadline_time")
    priority = data.get(
        "priority",
        "normal"
    )
    person = data.get("person")
    summary = data.get("summary")

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


    lines.append("")


    # =====================================================
    # GOOGLE RESULT
    # =====================================================

    if google_result:

        lines.append(
            "💾 Saved to Google Sheet ✅"
        )


        if google_result.get(
            "calendar_created"
        ):

            lines.append(
                "📅 Added to Google Calendar ✅"
            )


        if google_result.get(
            "drive_file_url"
        ):

            lines.append(
                "🖼 Saved to Google Drive ✅"
            )


    elif message_type == "conversation":

        lines.append(
            "💬 Conversation not stored"
        )


    else:

        lines.append(
            "⚠️ Save failed"
        )

        if save_error:

            lines.append(
                f"Reason: {save_error[:200]}"
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
        f"📥 Input: {prompt_tokens} tokens"
    )

    lines.append(
        f"📤 Output: {output_tokens} tokens"
    )


    if thinking_tokens > 0:

        lines.append(
            f"💭 Thinking: {thinking_tokens} tokens"
        )


    lines.append(
        f"📊 Total: {total_tokens} tokens"
    )


    return "\n".join(
        lines
    )


# =========================================================
# TEXT HANDLER
# =========================================================

@handler.add(
    MessageEvent,
    message=TextMessageContent
)
def handle_text_message(event):

    user_message = (
        event.message.text
    )

    try:

        result = analyze_text(
            user_message
        )

        google_result = None
        save_error = None


        if should_save(result):

            try:

                google_result = (
                    save_to_google(
                        result,
                        user_message
                    )
                )

            except Exception as error:

                save_error = str(error)


        reply_text = format_result(
            result,
            google_result,
            save_error
        )


    except Exception as error:

        reply_text = (
            "⚠️ AI Assistant error\n\n"
            + str(error)[:1000]
        )


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
# IMAGE HANDLER
# =========================================================

@handler.add(
    MessageEvent,
    message=ImageMessageContent
)
def handle_image_message(event):

    try:

        print(
            "Downloading image from LINE..."
        )


        with ApiClient(
            configuration
        ) as api_client:

            blob_api = MessagingApiBlob(
                api_client
            )

            image_bytes = (
                blob_api.get_message_content(
                    event.message.id
                )
            )


        print(
            "Image downloaded."
        )


        # =================================================
        # AI ANALYSIS
        # =================================================

        result = analyze_image(
            image_bytes
        )


        google_result = None
        save_error = None


        if should_save(result):

            try:

                google_result = (
                    save_to_google(
                        result,
                        "[Image from LINE]",
                        image_bytes=image_bytes
                    )
                )

            except Exception as error:

                save_error = str(error)


        reply_text = format_result(
            result,
            google_result,
            save_error
        )


    except Exception as error:

        print(
            "IMAGE ERROR:",
            str(error)
        )

        reply_text = (
            "⚠️ Image analysis failed\n\n"
            + str(error)[:1000]
        )


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