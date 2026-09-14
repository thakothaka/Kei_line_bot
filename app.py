import os
import json
import base64
import time
import re
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
    TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
    FileMessageContent,
)

from google import genai
from google.genai import types


# =========================================================
# APP / ENVIRONMENT
# =========================================================

APP_VERSION = "V8-WORK-ASSISTANT"
app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_APPS_SCRIPT_URL = os.getenv("GOOGLE_APPS_SCRIPT_URL")
GOOGLE_APPS_SCRIPT_SECRET = os.getenv("GOOGLE_APPS_SCRIPT_SECRET")

# Keep the default list conservative for a free-only setup.
# You can override in Render, e.g.
# GEMINI_MODELS=gemini-3.1-flash-lite,gemini-2.5-flash-lite
GEMINI_MODELS = [
    x.strip()
    for x in os.getenv(
        "GEMINI_MODELS",
        "gemini-3.1-flash-lite,gemini-2.5-flash-lite",
    ).split(",")
    if x.strip()
]

AI_DAILY_REQUEST_LIMIT = int(os.getenv("AI_DAILY_REQUEST_LIMIT", "60"))
AI_DAILY_TOKEN_LIMIT = int(os.getenv("AI_DAILY_TOKEN_LIMIT", "120000"))
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))
MAX_INLINE_FILE_BYTES = int(os.getenv("MAX_INLINE_FILE_BYTES", str(8 * 1024 * 1024)))

required_vars = {
    "LINE_CHANNEL_ACCESS_TOKEN": LINE_CHANNEL_ACCESS_TOKEN,
    "LINE_CHANNEL_SECRET": LINE_CHANNEL_SECRET,
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "GOOGLE_APPS_SCRIPT_URL": GOOGLE_APPS_SCRIPT_URL,
    "GOOGLE_APPS_SCRIPT_SECRET": GOOGLE_APPS_SCRIPT_SECRET,
}
for name, value in required_vars.items():
    if not value:
        raise RuntimeError(f"{name} is not set")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

PROJECT_CACHE = {"time": 0, "items": []}


# =========================================================
# WEB ROUTES
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return f"LINE AI Assistant {APP_VERSION} is running", 200


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK", 200


# =========================================================
# GOOGLE APPS SCRIPT API
# =========================================================

def google_api(action, payload=None, timeout=60):
    body = {
        "secret": GOOGLE_APPS_SCRIPT_SECRET,
        "action": action,
    }
    if payload:
        body.update(payload)

    response = requests.post(
        GOOGLE_APPS_SCRIPT_URL,
        json=body,
        timeout=timeout,
        allow_redirects=True,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Google Apps Script HTTP {response.status_code}: {response.text[:300]}"
        )

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(
            "Google Apps Script returned invalid JSON: " + response.text[:500]
        ) from exc

    if data.get("status") == "error":
        raise RuntimeError(data.get("message", "Google Apps Script error"))

    return data


def get_projects():
    now = time.time()
    if PROJECT_CACHE["items"] and now - PROJECT_CACHE["time"] < 300:
        return PROJECT_CACHE["items"]

    try:
        result = google_api("get_projects")
        projects = result.get("projects", [])
        PROJECT_CACHE["items"] = projects
        PROJECT_CACHE["time"] = now
        return projects
    except Exception as exc:
        print("PROJECT LOAD ERROR:", exc)
        return []


def get_usage_today(user_id):
    try:
        return google_api("get_usage_today", {"user_id": user_id}).get("usage", {})
    except Exception as exc:
        print("USAGE LOAD ERROR:", exc)
        return {}


def check_usage_guard(user_id):
    usage = get_usage_today(user_id)
    requests_today = int(usage.get("requests", 0) or 0)
    tokens_today = int(usage.get("total_tokens", 0) or 0)

    if requests_today >= AI_DAILY_REQUEST_LIMIT:
        raise RuntimeError(
            f"Daily AI safety limit reached ({requests_today}/{AI_DAILY_REQUEST_LIMIT} requests). "
            "Commands such as today, overdue, done, and usage still work."
        )

    if tokens_today >= AI_DAILY_TOKEN_LIMIT:
        raise RuntimeError(
            f"Daily AI token safety limit reached ({tokens_today}/{AI_DAILY_TOKEN_LIMIT} tokens). "
            "Commands such as today, overdue, done, and usage still work."
        )

    return usage


# =========================================================
# PROMPT / AI
# =========================================================

def build_prompt(projects):
    bangkok_time = datetime.now(ZoneInfo("Asia/Bangkok"))
    current_date = bangkok_time.strftime("%Y-%m-%d")
    current_weekday = bangkok_time.strftime("%A")

    project_lines = []
    for p in projects:
        name = p.get("project") or ""
        keywords = p.get("keywords") or ""
        if name:
            project_lines.append(f"- {name}: {keywords}")
    project_catalog = "\n".join(project_lines) if project_lines else "- No project catalog configured yet."

    return f"""
You are a personal work assistant.

Current date in Thailand: {current_date}
Today is: {current_weekday}
Timezone: Asia/Bangkok

KNOWN PROJECTS:
{project_catalog}

Use the known project names exactly when the content clearly matches their keywords.
If none matches, infer a concise project name or use null.

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
- PDF documents

IMPORTANT:
The content may contain MORE THAN ONE task, deadline, appointment, meeting,
reminder, idea, note, schedule item, or action.
Extract ALL meaningful items. Do not merge separate deadlines into one task.

Return JSON only using exactly this structure:

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
      "summary": "short summary",
      "confidence": 0.95,
      "date_inferred": false,
      "needs_confirmation": false,
      "confirmation_reason": null
    }}
  ]
}}

RULES:
1. Extract every separate meaningful item.
2. For tables/schedules, create one item per meaningful row.
3. type must be one of: task, reminder, idea, note, meeting.
4. task must be short and action-oriented when applicable.
5. deadline must be YYYY-MM-DD or null.
6. deadline_time must be HH:MM 24-hour format or null.
7. priority must be high, normal, or low.
8. Do not invent a deadline that is not present or reasonably implied.
9. Relative dates must use the current Thailand date.
10. If year is missing and you infer the upcoming year, set date_inferred=true.
11. confidence is 0.0 to 1.0 and should reflect confidence in task/date interpretation.
12. Set needs_confirmation=true if the date, time, task meaning, or item boundaries are ambiguous.
13. If the image has a common heading, use it as the project for related rows.
14. If there is no useful work information, return {{"items": []}}.
"""


def record_usage(user_id, model_name, usage, success=True, error=""):
    payload = {
        "user_id": user_id,
        "model": model_name,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "thinking_tokens": usage.get("thinking_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "success": bool(success),
        "error": error[:500],
    }
    try:
        return google_api("record_usage", payload).get("usage", {})
    except Exception as exc:
        print("USAGE RECORD ERROR:", exc)
        return {}


def call_gemini(contents, user_id):
    check_usage_guard(user_id)
    errors = []

    for index, model_name in enumerate(GEMINI_MODELS, start=1):
        try:
            print(f"Trying Gemini model: {model_name}")
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

            if not response.text:
                raise RuntimeError("Gemini returned an empty response")

            result = json.loads(response.text)
            items = result.get("items", [])
            if not isinstance(items, list):
                raise RuntimeError("Gemini response field 'items' is not a list")

            usage_meta = response.usage_metadata
            usage = {
                "input_tokens": getattr(usage_meta, "prompt_token_count", 0) or 0,
                "output_tokens": getattr(usage_meta, "candidates_token_count", 0) or 0,
                "thinking_tokens": getattr(usage_meta, "thoughts_token_count", 0) or 0,
                "total_tokens": getattr(usage_meta, "total_token_count", 0) or 0,
            }

            daily_usage = record_usage(user_id, model_name, usage, True, "")

            result["_model"] = model_name
            result["_attempt"] = index
            result["_usage"] = usage
            result["_daily_usage"] = daily_usage
            return result

        except Exception as exc:
            text = str(exc)
            print(f"Gemini model failed {model_name}: {text}")
            errors.append(f"{model_name}: {text[:250]}")
            continue

    record_usage(user_id, "ALL_FAILED", {}, False, " | ".join(errors))
    raise RuntimeError("All Gemini models failed:\n" + "\n".join(errors))


def analyze_text(text, user_id):
    prompt = build_prompt(get_projects())
    return call_gemini(prompt + "\n\nUSER MESSAGE:\n" + text, user_id)


def analyze_binary(file_bytes, mime_type, user_id, label="SOURCE FILE"):
    prompt = build_prompt(get_projects())
    file_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
    return call_gemini([prompt + f"\n\n{label}:\n", file_part], user_id)


def needs_confirmation(result):
    items = result.get("items", [])
    if not items:
        return False
    if len(items) > 10:
        return True

    for item in items:
        try:
            confidence = float(item.get("confidence", 1.0) or 0)
        except Exception:
            confidence = 0
        if confidence < CONFIDENCE_THRESHOLD:
            return True
        if item.get("date_inferred"):
            return True
        if item.get("needs_confirmation"):
            return True
    return False


# =========================================================
# COMMANDS
# =========================================================

def normalize_command(text):
    return re.sub(r"\s+", " ", text.strip())


def parse_command(text):
    raw = normalize_command(text)
    lower = raw.lower()

    exact_map = {
        "today": ("query", {"mode": "today"}),
        "วันนี้": ("query", {"mode": "today"}),
        "this week": ("query", {"mode": "week"}),
        "week": ("query", {"mode": "week"}),
        "สัปดาห์นี้": ("query", {"mode": "week"}),
        "overdue": ("query", {"mode": "overdue"}),
        "ค้าง": ("query", {"mode": "overdue"}),
        "usage": ("usage", {}),
        "quota": ("usage", {}),
        "projects": ("projects", {}),
        "help": ("help", {}),
        "save all": ("save_pending", {"force_duplicates": False}),
        "save all force": ("save_pending", {"force_duplicates": True}),
        "cancel": ("cancel_pending", {}),
    }
    if lower in exact_map:
        return exact_map[lower]

    m = re.match(r"^show project\s+(.+)$", raw, re.I)
    if m:
        return "query", {"mode": "project", "project": m.group(1).strip()}

    m = re.match(r"^done\s+(.+)$", raw, re.I)
    if m:
        return "done", {"target": m.group(1).strip()}

    m = re.match(r"^delete last(?:\s+(task|note|idea|reminder|meeting))?$", raw, re.I)
    if m:
        return "delete_last", {"type": (m.group(1) or "").lower()}

    m = re.match(
        r"^change deadline\s+(.+?)\s+(?:to\s+)?(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}:\d{2}))?$",
        raw,
        re.I,
    )
    if m:
        return "change_deadline", {
            "target": m.group(1).strip(),
            "deadline": m.group(2),
            "deadline_time": m.group(3) or "",
        }

    m = re.match(
        r"^edit\s+(\d+)\s+(task|project|deadline|time|deadline_time|priority|person|type|summary)\s+(.+)$",
        raw,
        re.I,
    )
    if m:
        field = m.group(2).lower()
        if field == "time":
            field = "deadline_time"
        return "edit_pending", {
            "index": int(m.group(1)),
            "field": field,
            "value": m.group(3).strip(),
        }

    return None


def execute_command(command, args, user_id):
    common = {"user_id": user_id}

    if command == "query":
        result = google_api("query_tasks", {**common, **args})
        return format_task_query(result)

    if command == "usage":
        result = google_api("get_usage_today", common)
        return format_usage(result.get("usage", {}))

    if command == "help":
        return (
            "🤖 Commands\n"
            "• today\n• this week\n• overdue\n• show project <name>\n"
            "• done <Task ID or task words>\n• delete last [task/note/idea]\n"
            "• change deadline <Task ID or words> to YYYY-MM-DD [HH:MM]\n"
            "• usage\n• projects\n• save all\n• save all force\n• cancel\n"
            "• edit 2 deadline 2026-09-20\n• edit 2 time 14:00"
        )

    if command == "projects":
        projects = get_projects()
        if not projects:
            return "📁 No projects configured yet. Add rows to the Projects tab: Project | Keywords | Active"
        lines = ["📁 Projects"]
        for p in projects[:30]:
            lines.append(f"• {p.get('project')} — {p.get('keywords', '')}")
        return "\n".join(lines)

    if command == "done":
        result = google_api("mark_done", {**common, **args})
        return f"✅ Done: {result.get('task_id', '')} {result.get('task', '')}".strip()

    if command == "delete_last":
        result = google_api("delete_last", {**common, **args})
        return f"🗑 Deleted: {result.get('task_id', '')} {result.get('task', '')}".strip()

    if command == "change_deadline":
        result = google_api("change_deadline", {**common, **args})
        text = f"📅 Updated {result.get('task_id', '')}: {result.get('deadline', '')}"
        if result.get("deadline_time"):
            text += " " + result.get("deadline_time")
        return text

    if command == "save_pending":
        result = google_api("save_pending", {**common, **args}, timeout=90)
        return format_save_result(result)

    if command == "cancel_pending":
        google_api("cancel_pending", common)
        return "❌ Pending items cancelled."

    if command == "edit_pending":
        result = google_api("edit_pending", {**common, **args})
        return format_pending(result)

    return "Unknown command."


# =========================================================
# GOOGLE PREPARE / PENDING
# =========================================================

def prepare_items(
    result,
    user_id,
    original_message,
    source_kind="text",
    file_bytes=None,
    file_mime_type="",
    file_name="",
):
    items = result.get("items", [])
    if not items:
        return {"status": "success", "pending": False, "saved_count": 0}

    payload = {
        "user_id": user_id,
        "items": items,
        "original_message": original_message,
        "source_kind": source_kind,
        "source_file_name": file_name,
        "request_confirmation": needs_confirmation(result),
    }

    if file_bytes:
        payload["file_base64"] = base64.b64encode(file_bytes).decode("utf-8")
        payload["file_mime_type"] = file_mime_type

    return google_api("prepare_items", payload, timeout=90)


# =========================================================
# FORMATTERS
# =========================================================

def item_label(item, idx=None):
    prefix = f"{idx}. " if idx is not None else ""
    title = item.get("task") or item.get("summary") or "Item"
    lines = [prefix + title]

    if item.get("project"):
        lines.append(f"   📁 {item.get('project')}")
    if item.get("deadline"):
        d = item.get("deadline")
        if item.get("deadline_time"):
            d += " " + item.get("deadline_time")
        lines.append(f"   📅 {d}")
    if item.get("priority"):
        lines.append(f"   ⭐ {item.get('priority')}")
    if item.get("person"):
        lines.append(f"   👤 {item.get('person')}")
    conf = item.get("confidence")
    if conf is not None:
        try:
            lines.append(f"   🎯 {float(conf):.0%} confidence")
        except Exception:
            pass
    return "\n".join(lines)


def format_pending(result):
    items = result.get("items", [])
    duplicates = result.get("duplicates", [])
    lines = ["🤖 Please confirm before saving", ""]
    for i, item in enumerate(items, 1):
        lines.append(item_label(item, i))
        lines.append("")

    if duplicates:
        lines.append(f"⚠️ Possible duplicate(s): {len(duplicates)}")
        for d in duplicates[:5]:
            lines.append(f"• {d.get('task')} — {d.get('deadline', '')}")
        lines.append("")

    if result.get("drive_file_url"):
        lines.append("🗂 Source file temporarily saved to Drive")

    lines.extend([
        "Reply:",
        "• save all",
        "• save all force  (also save duplicates)",
        "• edit 2 deadline 2026-09-20",
        "• edit 2 time 14:00",
        "• edit 2 task New task name",
        "• cancel",
    ])
    return "\n".join(lines)


def format_save_result(result):
    lines = []
    saved = int(result.get("saved_count", 0) or 0)
    cal = int(result.get("calendar_count", 0) or 0)
    dup = int(result.get("duplicate_skipped_count", 0) or 0)
    lines.append(f"💾 {saved} item(s) saved to Google Sheet ✅")
    if cal:
        lines.append(f"📅 {cal} Calendar event(s) created ✅")
    if result.get("drive_file_url"):
        lines.append("🗂 Source file saved to Google Drive ✅")
    if dup:
        lines.append(f"⚠️ {dup} duplicate item(s) skipped")
    task_ids = result.get("task_ids", [])
    if task_ids:
        lines.append("IDs: " + ", ".join(task_ids[:10]))
    return "\n".join(lines)


def format_analysis(result, google_result=None):
    items = result.get("items", [])
    lines = ["🤖 AI Assistant", ""]

    if not items:
        lines.append("No work item detected.")
    else:
        lines.append(f"Found {len(items)} item(s)")
        lines.append("")
        for i, item in enumerate(items, 1):
            lines.append(item_label(item, i))
            lines.append("")

    if google_result:
        if google_result.get("pending"):
            return format_pending(google_result) + "\n\n" + format_ai_status(result)
        lines.append(format_save_result(google_result))

    lines.append("")
    lines.append(format_ai_status(result))
    return "\n".join(lines).strip()


def format_ai_status(result):
    usage = result.get("_usage", {})
    daily = result.get("_daily_usage", {})
    attempt = int(result.get("_attempt", 1) or 1)
    lines = ["──────────────", "⚙️ AI Status"]
    lines.append("✅ Primary model" if attempt == 1 else f"🔄 Fallback #{attempt - 1}")
    lines.append(f"🧠 Model: {result.get('_model', 'Unknown')}")
    lines.append(f"📥 Input: {usage.get('input_tokens', 0)} tokens")
    lines.append(f"📤 Output: {usage.get('output_tokens', 0)} tokens")
    if usage.get("thinking_tokens", 0):
        lines.append(f"💭 Thinking: {usage.get('thinking_tokens', 0)} tokens")
    lines.append(f"📊 This request: {usage.get('total_tokens', 0)} tokens")
    if daily:
        lines.append(
            f"📈 Today: {daily.get('requests', 0)} requests / "
            f"{daily.get('total_tokens', 0)} tokens"
        )
        lines.append(
            f"🛡 Safety cap: {AI_DAILY_REQUEST_LIMIT} requests / {AI_DAILY_TOKEN_LIMIT} tokens"
        )
    return "\n".join(lines)


def format_usage(usage):
    return (
        "📊 AI Usage Today\n"
        f"Requests: {usage.get('requests', 0)} / {AI_DAILY_REQUEST_LIMIT}\n"
        f"Input tokens: {usage.get('input_tokens', 0)}\n"
        f"Output tokens: {usage.get('output_tokens', 0)}\n"
        f"Thinking tokens: {usage.get('thinking_tokens', 0)}\n"
        f"Total tokens: {usage.get('total_tokens', 0)} / {AI_DAILY_TOKEN_LIMIT}\n\n"
        "These are your bot's own safety counters, not Google's official remaining quota."
    )


def format_task_query(result):
    tasks = result.get("tasks", [])
    title = result.get("title", "Tasks")
    if not tasks:
        return f"📋 {title}\nNo matching tasks."
    lines = [f"📋 {title}"]
    for item in tasks[:20]:
        line = f"• {item.get('task_id', '')} {item.get('task', '')}".strip()
        if item.get("deadline"):
            line += f" — {item.get('deadline')}"
            if item.get("deadline_time"):
                line += f" {item.get('deadline_time')}"
        if item.get("status"):
            line += f" [{item.get('status')}]"
        lines.append(line)
    return "\n".join(lines)


# =========================================================
# LINE REPLY
# =========================================================

def reply_line(reply_token, text):
    # LINE text message max is large, but keep replies practical.
    if len(text) > 4500:
        text = text[:4450] + "\n\n…reply shortened"

    with ApiClient(configuration) as api_client:
        line_api = MessagingApi(api_client)
        line_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )


def event_user_id(event):
    try:
        return event.source.user_id or ""
    except Exception:
        return ""


# =========================================================
# TEXT HANDLER
# =========================================================

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_message = event.message.text
    user_id = event_user_id(event)

    try:
        parsed = parse_command(user_message)
        if parsed:
            command, args = parsed
            reply_line(event.reply_token, execute_command(command, args, user_id))
            return

        result = analyze_text(user_message, user_id)
        google_result = None
        if result.get("items"):
            google_result = prepare_items(
                result=result,
                user_id=user_id,
                original_message=user_message,
                source_kind="text",
            )
        reply_line(event.reply_token, format_analysis(result, google_result))

    except Exception as exc:
        print("TEXT ERROR:", exc)
        reply_line(event.reply_token, "⚠️ AI Assistant error\n\n" + str(exc)[:1200])


# =========================================================
# IMAGE HANDLER
# =========================================================

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    user_id = event_user_id(event)
    try:
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            image_bytes = blob_api.get_message_content(event.message.id)

        if len(image_bytes) > MAX_INLINE_FILE_BYTES:
            raise RuntimeError(
                f"Image is too large for the safe inline limit ({MAX_INLINE_FILE_BYTES // 1024 // 1024} MB)."
            )

        mime_type = "image/jpeg"
        result = analyze_binary(image_bytes, mime_type, user_id, "IMAGE")
        google_result = None
        if result.get("items"):
            google_result = prepare_items(
                result=result,
                user_id=user_id,
                original_message="[Image from LINE]",
                source_kind="image",
                file_bytes=image_bytes,
                file_mime_type=mime_type,
                file_name=f"LINE_image_{datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%Y%m%d_%H%M%S')}.jpg",
            )
        reply_line(event.reply_token, format_analysis(result, google_result))

    except Exception as exc:
        print("IMAGE ERROR:", exc)
        reply_line(event.reply_token, "⚠️ Image analysis failed\n\n" + str(exc)[:1200])


# =========================================================
# PDF / FILE HANDLER
# =========================================================

@handler.add(MessageEvent, message=FileMessageContent)
def handle_file_message(event):
    user_id = event_user_id(event)
    file_name = getattr(event.message, "file_name", "LINE_file") or "LINE_file"
    lower_name = file_name.lower()

    if not lower_name.endswith(".pdf"):
        reply_line(
            event.reply_token,
            "📎 File received. For now, document analysis supports PDF files. Images are also supported directly.",
        )
        return

    try:
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            file_bytes = blob_api.get_message_content(event.message.id)

        if len(file_bytes) > MAX_INLINE_FILE_BYTES:
            raise RuntimeError(
                f"PDF is too large for the safe inline limit ({MAX_INLINE_FILE_BYTES // 1024 // 1024} MB)."
            )

        mime_type = "application/pdf"
        result = analyze_binary(file_bytes, mime_type, user_id, "PDF DOCUMENT")
        google_result = None
        if result.get("items"):
            google_result = prepare_items(
                result=result,
                user_id=user_id,
                original_message=f"[PDF from LINE: {file_name}]",
                source_kind="pdf",
                file_bytes=file_bytes,
                file_mime_type=mime_type,
                file_name=file_name,
            )
        reply_line(event.reply_token, format_analysis(result, google_result))

    except Exception as exc:
        print("PDF ERROR:", exc)
        reply_line(event.reply_token, "⚠️ PDF analysis failed\n\n" + str(exc)[:1200])


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
