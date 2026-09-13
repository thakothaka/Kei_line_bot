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
# AI PROMPT
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
- tables
- schedules
- meeting notes
- email screenshots
- documents shown in images

IMPORTANT:

The content may contain MORE THAN ONE:
- task
- deadline
- appointment
- meeting
- schedule item
- reminder
- action

You MUST extract ALL meaningful items.

Do NOT select only one item.

Return JSON only.

Use exactly this structure:

{{
  "items": [
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
  ]
}}

RULES:

1. Extract EVERY separate actionable item.

2. If a table has multiple rows,
create one item for each meaningful row.

3. If several rows belong to one process,
use the common heading as the project.

Example:

Heading:
Visa Process

Rows:
Health Check-up
Visa Application
Signing Documents

Then project should be:
Visa Process

for all items.

4. type must be one of:

task
reminder
idea
note
meeting

5. task:
Short and clear description.

6. project:
Identify the project or work topic.
Otherwise null.

7. deadline:
Use YYYY-MM-DD.
Otherwise null.

8. deadline_time:
Use HH:MM in 24-hour format.
Otherwise null.

9. priority:
high
normal
low

10. person:
Important person involved.
Otherwise null.

11. summary:
Short useful summary.

12. Convert relative dates using
the current Thailand date.

Examples:

tomorrow
= next calendar day

Friday
= next upcoming Friday

วันพรุ่งนี้
= tomorrow

วันศุกร์
= next upcoming Friday

13. If the year is missing,
infer the most reasonable upcoming year
based on the current Thailand date.

14. Do not invent deadlines.

15. If an image contains a schedule table,
preserve every separate schedule row.

16. If one row contains a location,
include the location in the summary.

17. If there is no useful work information,
return:

{{
  "items": []
}}

18. Do NOT merge several deadlines
into one task.
"""


# =========================================================
# GEMINI CALL WITH FALLBACK
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

            attempt_number = (
                model_index + 1
            )

            print(
                f"Trying Gemini model: "
                f"{model_name}"
            )

            response = (
                gemini_client
                .models
                .generate_content(
                    model=model_name,
                    contents=contents,
                    config=
                    types.GenerateContentConfig(
                        response_mime_type=
                        "application/json",
                        temperature=0.1
                    )
                )
            )

            if not response.text:

                raise RuntimeError(
                    "Gemini returned "
                    "an empty response"
                )

            print(
                "Gemini raw response:"
            )

            print(
                response.text
            )

            result = json.loads(
                response.text
            )

            items = result.get(
                "items",
                []
            )

            if not isinstance(
                items,
                list
            ):

                raise RuntimeError(
                    "Gemini items is not a list"
                )

            # =============================================
            # TOKEN USAGE
            # =============================================

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
                "Gemini success:"
            )

            print(
                f"Model: {model_name}"
            )

            print(
                f"Items found: "
                f"{len(items)}"
            )

            return result

        except Exception as error:

            error_text = str(
                error
            )

            print(
                "Gemini model failed:"
            )

            print(
                model_name
            )

            print(
                error_text
            )

            errors.append(
                f"{model_name}: "
                f"{error_text[:250]}"
            )

    raise RuntimeError(
        "All Gemini models failed:\n"
        +
        "\n".join(errors)
    )


# =========================================================
# ANALYZE TEXT
# =========================================================

def analyze_text(user_message):

    prompt = build_prompt()

    full_prompt = (
        prompt
        +
        "\n\nUSER MESSAGE:\n"
        +
        user_message
    )

    return call_gemini(
        full_prompt
    )


# =========================================================
# ANALYZE IMAGE
# =========================================================

def analyze_image(
    image_bytes,
    mime_type="image/jpeg"
):

    prompt = build_prompt()

    image_part = (
        types.Part.from_bytes(
            data=image_bytes,
            mime_type=mime_type
        )
    )

    contents = [
        prompt,
        image_part
    ]

    return call_gemini(
        contents
    )


# =========================================================
# SAVE MULTIPLE ITEMS TO GOOGLE
# =========================================================

def save_to_google(
    items,
    original_message,
    image_bytes=None,
    image_mime_type=None
):

    payload = {

        "secret":
            GOOGLE_APPS_SCRIPT_SECRET,

        "original_message":
            original_message,

        "items":
            items
    }

    # =====================================================
    # IMAGE
    # =====================================================

    if image_bytes:

        image_base64 = (
            base64
            .b64encode(
                image_bytes
            )
            .decode(
                "utf-8"
            )
        )

        payload[
            "image_base64"
        ] = image_base64

        payload[
            "image_mime_type"
        ] = (
            image_mime_type
            or
            "image/jpeg"
        )

    print(
        "Sending to Google Apps Script..."
    )

    response = requests.post(
        GOOGLE_APPS_SCRIPT_URL,
        json=payload,
        timeout=90,
        allow_redirects=True
    )

    print(
        "Google HTTP status:",
        response.status_code
    )

    print(
        "Google response:"
    )

    print(
        response.text[:2000]
    )

    if response.status_code != 200:

        raise RuntimeError(
            "Google Apps Script HTTP "
            +
            str(response.status_code)
        )

    try:

        result = response.json()

    except Exception:

        raise RuntimeError(
            "Google Apps Script returned "
            "invalid JSON: "
            +
            response.text[:500]
        )

    if (
        result.get("status")
        !=
        "success"
    ):

        raise RuntimeError(
            result.get(
                "message",
                "Google save failed"
            )
        )

    return result


# =========================================================
# FORMAT MULTIPLE ITEMS
# =========================================================

def format_result(
    result,
    google_result=None,
    save_error=None
):

    items = result.get(
        "items",
        []
    )

    model = result.get(
        "_model",
        "Unknown"
    )

    attempt = result.get(
        "_attempt",
        1
    )

    prompt_tokens = result.get(
        "_prompt_tokens",
        0
    )

    output_tokens = result.get(
        "_output_tokens",
        0
    )

    thinking_tokens = result.get(
        "_thinking_tokens",
        0
    )

    total_tokens = result.get(
        "_total_tokens",
        0
    )

    lines = []

    lines.append(
        "🤖 AI Assistant"
    )

    lines.append("")

    # =====================================================
    # NO ITEMS
    # =====================================================

    if len(items) == 0:

        lines.append(
            "No work item detected."
        )

    # =====================================================
    # ITEMS
    # =====================================================

    else:

        lines.append(
            f"Found {len(items)} item(s)"
        )

        for index, item in enumerate(
            items,
            start=1
        ):

            lines.append("")

            lines.append(
                f"{index}. "
                f"{item.get('task') or item.get('summary') or 'Item'}"
            )

            project = item.get(
                "project"
            )

            deadline = item.get(
                "deadline"
            )

            deadline_time = item.get(
                "deadline_time"
            )

            priority = item.get(
                "priority"
            )

            person = item.get(
                "person"
            )

            item_type = item.get(
                "type"
            )

            if item_type:

                lines.append(
                    f"   🏷 {item_type}"
                )

            if project:

                lines.append(
                    f"   📁 {project}"
                )

            if deadline:

                deadline_text = (
                    deadline
                )

                if deadline_time:

                    deadline_text += (
                        f" {deadline_time}"
                    )

                lines.append(
                    f"   📅 {deadline_text}"
                )

            if priority:

                lines.append(
                    f"   ⭐ {priority}"
                )

            if person:

                lines.append(
                    f"   👤 {person}"
                )

    # =====================================================
    # GOOGLE STATUS
    # =====================================================

    lines.append("")

    if google_result:

        saved_count = (
            google_result.get(
                "saved_count",
                len(items)
            )
        )

        calendar_count = (
            google_result.get(
                "calendar_count",
                0
            )
        )

        drive_file_url = (
            google_result.get(
                "drive_file_url"
            )
        )

        lines.append(
            f"💾 {saved_count} item(s) "
            f"saved to Google Sheet ✅"
        )

        if calendar_count > 0:

            lines.append(
                f"📅 {calendar_count} event(s) "
                f"added to Google Calendar ✅"
            )

        if drive_file_url:

            lines.append(
                "🖼 Image saved to "
                "Google Drive ✅"
            )

    elif save_error:

        lines.append(
            "⚠️ Google save failed"
        )

        lines.append(
            f"Reason: "
            f"{save_error[:300]}"
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

        items = result.get(
            "items",
            []
        )

        google_result = None
        save_error = None

        if len(items) > 0:

            try:

                google_result = (
                    save_to_google(
                        items=items,
                        original_message=
                            user_message
                    )
                )

            except Exception as error:

                save_error = str(
                    error
                )

        reply_text = format_result(
            result,
            google_result,
            save_error
        )

    except Exception as error:

        print(
            "TEXT ERROR:",
            str(error)
        )

        reply_text = (
            "⚠️ AI Assistant error\n\n"
            +
            str(error)[:1000]
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

        # =================================================
        # DOWNLOAD IMAGE
        # =================================================

        with ApiClient(
            configuration
        ) as api_client:

            blob_api = (
                MessagingApiBlob(
                    api_client
                )
            )

            image_bytes = (
                blob_api
                .get_message_content(
                    event.message.id
                )
            )

        print(
            "Image downloaded:"
        )

        print(
            len(image_bytes),
            "bytes"
        )

        # LINE image content is normally JPEG
        mime_type = "image/jpeg"

        # =================================================
        # GEMINI ANALYSIS
        # =================================================

        result = analyze_image(
            image_bytes,
            mime_type
        )

        items = result.get(
            "items",
            []
        )

        google_result = None
        save_error = None

        # =================================================
        # SAVE IMAGE + ALL ITEMS
        # =================================================

        if len(items) > 0:

            try:

                google_result = (
                    save_to_google(
                        items=items,
                        original_message=
                            "[Image from LINE]",
                        image_bytes=
                            image_bytes,
                        image_mime_type=
                            mime_type
                    )
                )

            except Exception as error:

                save_error = str(
                    error
                )

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
            +
            str(error)[:1000]
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