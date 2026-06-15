#!/usr/bin/env python3
"""
Roblox Studio MCP Client
────────────────────────
A command-line interface for the Roblox Studio MCP server.
Supports single tool calls, AI-assisted batches, and manual batch mode.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from collections import deque
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG  —  edit these to enable API mode
# ══════════════════════════════════════════════════════════════════════════════
API_KEY   = "sk-or-v1-YOUR_API_KEY_HERE" # Your api key here.
API_URL   = "https://openrouter.ai/api/v1/chat/completions" # Openrouter provider is default, however you can change this at any time.
API_MODEL = "openai/gpt-oss-120b:free" # Default model used.
# ══════════════════════════════════════════════════════════════════════════════
MCP_BAT = os.path.expandvars(r"%LOCALAPPDATA%\Roblox\mcp.bat")
INSTRUCTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instructions.txt")

# Output history ring-buffer — newest first (index 0 == most recent)
OUTPUT_HISTORY: deque[dict] = deque(maxlen=100)

# ── Tool schema ───────────────────────────────────────────────────────────────
TOOLS: dict[str, dict[str, dict]] = {
    "execute_luau": {
        "code":           {"type": "string", "required": True,  "desc": "Luau code to execute"},
        "datamodel_type": {"type": "enum",   "required": True,  "desc": "Edit | Client | Server",
                           "enum": ["Edit", "Client", "Server"]},
    },
    "set_active_studio": {
        "studio_id": {"type": "string", "required": True, "desc": "Studio instance ID from list_roblox_studios"},
    },
    "script_grep": {
        "query": {"type": "string", "required": True, "desc": "String or Luau pattern to search for"},
    },
    "subagent": {
        "description":   {"type": "string", "required": True, "desc": "Short 3-5 word task description"},
        "subagent_type": {"type": "enum",   "required": True, "desc": "explore | playtest | screen_capture",
                          "enum": ["explore", "playtest", "screen_capture"]},
        "task":          {"type": "string", "required": True, "desc": "Detailed task instructions for the subagent"},
    },
    "get_studio_state":    {},
    "list_roblox_studios": {},
    "get_console_output":  {},
    "screen_capture": {
        "capture_id":      {"type": "string", "required": True,  "desc": "Capture identifier, e.g. 'ScreenCapture_1'"},
        "camera_position": {"type": "json",   "required": False, "desc": "[x, y, z] world position of the camera"},
        "look_at_position":{"type": "json",   "required": False, "desc": "[x, y, z] world position to look at"},
    },
    "user_mouse_input": {
        "actions":        {"type": "json", "required": True, "desc": "Array of mouse action objects"},
        "datamodel_type": {"type": "enum", "required": True, "desc": "Client only",
                           "enum": ["Client"]},
    },
    "user_keyboard_input": {
        "actions":        {"type": "json", "required": True, "desc": "Array of keyboard action objects"},
        "datamodel_type": {"type": "enum", "required": True, "desc": "Client only",
                           "enum": ["Client"]},
    },
    "character_navigation": {
        "datamodel_type":   {"type": "enum",   "required": True,  "desc": "Client only", "enum": ["Client"]},
        "instance_path":    {"type": "string", "required": False, "desc": "Dot-path to navigate to, e.g. game.Workspace.Part"},
        "speed_multiplier": {"type": "number", "required": False, "desc": "0.1–10.0, default 1.0"},
        "x":                {"type": "number", "required": False, "desc": "X coordinate (if no instance_path)"},
        "y":                {"type": "number", "required": False, "desc": "Y coordinate (if no instance_path)"},
        "z":                {"type": "number", "required": False, "desc": "Z coordinate (if no instance_path)"},
    },
    "insert_from_creator_store": {
        "searchId":    {"type": "string", "required": True,  "desc": "ID returned by search_creator_store"},
        "assetName":   {"type": "string", "required": False, "desc": "Optional display name override"},
        "objectTypes": {"type": "json",   "required": False, "desc": "Optional array of objectTypes to restrict"},
    },
    "generate_mesh": {
        "textPrompt":   {"type": "string", "required": True,  "desc": "Description of the mesh to generate"},
        "maxTriangles": {"type": "number", "required": False, "desc": "12–20000"},
        "partNames":    {"type": "string", "required": False, "desc": "Comma-separated part name schema"},
        "size":         {"type": "json",   "required": False, "desc": '{"x":4,"y":4,"z":4} bounding box'},
    },
    "generate_procedural_model": {
        "prompt":           {"type": "string", "required": True,  "desc": "Description of what to create"},
        "attachedImageUri": {"type": "string", "required": False, "desc": "IMAGEID_<id> from store_image"},
        "partNames":        {"type": "string", "required": False, "desc": "Comma-separated part name schema"},
    },
    "generate_material": {
        "materialId":          {"type": "string", "required": True, "desc": "Unique ID you assign for this material, e.g. 'mat_lava_01'"},
        "materialDescription": {"type": "string", "required": True, "desc": "Text description of the desired material"},
        "baseMaterial":        {"type": "enum",   "required": True, "desc": "Roblox base material to derive from",
                                "enum": ["Plastic","SmoothPlastic","Wood","WoodPlanks","Marble","Basalt","Slate",
                                         "CrackedLava","Concrete","Limestone","Granite","Pavement","Brick","Pebble",
                                         "Cobblestone","Rock","Sandstone","CorrodedMetal","DiamondPlate","Foil",
                                         "Metal","Grass","LeafyGrass","Sand","Fabric","Snow","Mud","Ground",
                                         "Asphalt","Salt","Ice","Glacier","Cardboard","Carpet","CeramicTiles",
                                         "ClayRoofTiles","RoofShingles","Leather","Plaster","Rubber"]},
        "materialPattern":     {"type": "enum",   "required": True, "desc": "Regular | Organic",
                                "enum": ["Regular","Organic"]},
    },
    "wait_job_finished": {
        "generationId": {"type": "string", "required": True,  "desc": "Generation ID from generate_procedural_model"},
        "timeout":      {"type": "number", "required": False, "desc": "Seconds to wait (default 600)"},
    },
    "multi_edit": {
        "datamodel_type": {"type": "enum",   "required": True,  "desc": "Edit only", "enum": ["Edit"]},
        "file_path":      {"type": "string", "required": True,  "desc": "Dot-notation script path"},
        "edits":          {"type": "json",   "required": True,  "desc": 'Array of {"old_string","new_string"} objects'},
        "className":      {"type": "string", "required": False, "desc": "Required only when creating new scripts"},
    },
    "upload_image": {
        "imagePaths": {"type": "json", "required": True, "desc": "Array of local image path strings"},
    },
    "start_stop_play": {
        "is_start": {"type": "bool", "required": True, "desc": "true to start play, false to stop"},
    },
    "search_creator_store": {
        "query": {"type": "string", "required": True, "desc": "Search query for assets"},
    },
    "script_search": {
        "keywords": {"type": "string", "required": True, "desc": "Comma-separated keywords"},
    },
    "store_image": {
        "filePath": {"type": "string", "required": True, "desc": "Absolute path to local image (png/jpg/jpeg)"},
    },
    "inspect_instance": {
        "path": {"type": "string", "required": True, "desc": "Dot-notation instance path (case-insensitive), e.g. game.Workspace.RedPart"},
    },
    "search_game_tree": {
        "path":          {"type": "string", "required": False, "desc": "Start path, e.g. 'Workspace' or 'ServerScriptService.MyFolder'"},
        "keywords":      {"type": "string", "required": False, "desc": "Comma-separated name keywords (case-insensitive)"},
        "instance_type": {"type": "string", "required": False, "desc": "Filter by ClassName via IsA(), e.g. 'BasePart', 'BaseScript'. Case-sensitive."},
        "max_depth":     {"type": "number", "required": False, "desc": "Traversal depth from start point (default 3, max 10)"},
        "head_limit":    {"type": "number", "required": False, "desc": "Max results to return (default 200)"},
    },
    "script_read": {
        "target_file":                    {"type": "string", "required": True,  "desc": "Dot-notation script path, e.g. game.ServerScriptService.MyScript"},
        "should_read_entire_file":        {"type": "bool",   "required": False, "desc": "Read the whole file (default true). Set false to use line range."},
        "start_line_one_indexed":         {"type": "number", "required": False, "desc": "First line to read (1-indexed). Required if should_read_entire_file is false."},
        "end_line_one_indexed_inclusive": {"type": "number", "required": False, "desc": "Last line to read inclusive. Required if should_read_entire_file is false."},
    },
    "skill": {
        "skill_name": {"type": "string", "required": True, "desc": "Name of the skill to retrieve"},
    },
    "http_get": {
        "url": {"type": "string", "required": True, "desc": "URL to fetch via HTTP GET"},
    },
}

TOOL_NAMES = sorted(TOOLS.keys())

# ── Built-in command names (not forwarded to MCP) ─────────────────────────────
BUILTINS = {"help", "output", "clear", "run", "exit", "quit", "history"}


# ══════════════════════════════════════════════════════════════════════════════
# $ref resolution
# ══════════════════════════════════════════════════════════════════════════════

def resolve_refs(value: Any) -> Any:
    """Recursively walk a parsed JSON value and resolve any $ref strings."""
    if isinstance(value, dict):
        return {k: resolve_refs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_refs(v) for v in value]
    if isinstance(value, str) and value.startswith("$ref "):
        return resolve_ref_string(value)
    return value


def resolve_ref_string(ref: str) -> Any:
    """
    Resolve a $ref string of the form:  $ref <index> <variable_name>
    index 1 = most recently completed tool call output.
    """
    parts = ref.split(" ", 2)
    if len(parts) != 3:
        print(f"  [warn] Malformed $ref (expected '$ref <index> <variable>'): {ref!r}")
        return ref

    _, raw_index, var_name = parts
    try:
        index = int(raw_index)
    except ValueError:
        print(f"  [warn] $ref index must be an integer, got: {raw_index!r}")
        return ref

    if index < 1 or index > len(OUTPUT_HISTORY):
        print(f"  [warn] $ref index {index} out of range (history has {len(OUTPUT_HISTORY)} entries)")
        return ref

    # History is newest-first: index 1 = [0], index 2 = [1], ...
    entry = list(OUTPUT_HISTORY)[index - 1]
    raw_text: str = entry.get("raw", "")

    # 1. Try JSON parse
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict) and var_name in parsed:
            return parsed[var_name]
        # Search nested
        result = _find_key_in_json(parsed, var_name)
        if result is not None:
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Regex: "var_name": "value"  or  "var_name": 123
    pattern = rf'"{re.escape(var_name)}"\s*:\s*("(?:[^"\\]|\\.)*"|\d+(?:\.\d+)?|true|false|null)'
    m = re.search(pattern, raw_text)
    if m:
        raw_val = m.group(1)
        try:
            return json.loads(raw_val)
        except json.JSONDecodeError:
            return raw_val

    # 3. Plain text: var_name: value
    pattern2 = rf'\b{re.escape(var_name)}\s*[=:]\s*(\S+)'
    m2 = re.search(pattern2, raw_text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip(",;\"'")

    print(f"  [warn] $ref could not find '{var_name}' in output at index {index}")
    return ref


def _find_key_in_json(obj: Any, key: str) -> Any:
    """Recursively search for a key in a parsed JSON structure."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            result = _find_key_in_json(v, key)
            if result is not None:
                return result
    if isinstance(obj, list):
        for item in obj:
            result = _find_key_in_json(item, key)
            if result is not None:
                return result
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Argument parsing / coercion
# ══════════════════════════════════════════════════════════════════════════════

def coerce(value: Any, typ: str, meta: dict) -> Any:
    if typ == "number":
        if isinstance(value, (int, float)):
            return value
        try:
            return int(str(value))
        except ValueError:
            return float(str(value))
    if typ == "bool":
        if isinstance(value, bool):
            return value
        s = str(value).lower()
        if s in ("true", "1", "yes"):
            return True
        if s in ("false", "0", "no"):
            return False
        raise ValueError(f"Cannot parse {value!r} as bool — use true/false")
    if typ == "json":
        if isinstance(value, (dict, list)):
            return value
        return json.loads(str(value))
    if typ == "enum":
        if value not in meta.get("enum", []):
            opts = " | ".join(meta["enum"])
            raise ValueError(f"Must be one of: {opts}")
        return value
    return value  # string


def parse_args(raw: str, schema: dict[str, dict]) -> tuple[dict[str, Any] | None, str | None]:
    """
    Parse raw JSON string against tool schema.
    Returns (args_dict, None) on success or (None, error_message) on failure.
    """
    raw = raw.strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {e}"
        if not isinstance(parsed, dict):
            return None, "Arguments must be a JSON object { ... }"
    else:
        parsed = {}

    result: dict[str, Any] = {}
    for name, meta in schema.items():
        if name in parsed:
            raw_val = parsed[name]
            # Resolve $ref if it appears as a string value
            if isinstance(raw_val, str) and raw_val.startswith("$ref "):
                raw_val = resolve_ref_string(raw_val)
            try:
                result[name] = coerce(raw_val, meta["type"], meta)
            except (ValueError, json.JSONDecodeError) as e:
                return None, f"Parameter '{name}': {e}"
        elif meta["required"]:
            return None, f"Missing required parameter: '{name}' — {meta['desc']}"

    unknown = set(parsed) - set(schema)
    if unknown:
        print(f"  [warn] Unknown parameter(s) ignored: {', '.join(sorted(unknown))}")

    return result, None


# ══════════════════════════════════════════════════════════════════════════════
# Output formatting
# ══════════════════════════════════════════════════════════════════════════════

def format_result(content: Any) -> str:
    if isinstance(content, list):
        parts = []
        for item in content:
            if hasattr(item, "text"):
                parts.append(item.text)
            elif hasattr(item, "type"):
                parts.append(f"[{item.type}]")
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def push_output(tool_name: str, text: str) -> None:
    """Add a tool result to the front of output history (index 1)."""
    OUTPUT_HISTORY.appendleft({"tool": tool_name, "raw": text})


# ══════════════════════════════════════════════════════════════════════════════
# Help
# ══════════════════════════════════════════════════════════════════════════════

def print_help(tool: str | None = None) -> None:
    if tool:
        if tool not in TOOLS:
            print(f"Unknown tool: {tool}")
            return
        schema = TOOLS[tool]
        print(f"\n  {tool}")
        if not schema:
            print("    (no parameters)")
        for name, meta in schema.items():
            req  = "required" if meta["required"] else "optional"
            typ  = "|".join(meta["enum"]) if meta.get("enum") else meta["type"]
            print(f"    {name}  <{typ}>  [{req}]")
            print(f"      {meta['desc']}")
        print()
    else:
        print("\nAvailable tools:")
        for name in TOOL_NAMES:
            schema   = TOOLS[name]
            required = [k for k, v in schema.items() if v.get("required")]
            sig      = "  " + name
            if required:
                sig += "  {" + ", ".join(f'"{p}": ...' for p in required) + "}"
            print(sig)
        print()
        print("Built-in commands:")
        print("  help [tool]   Tool list, or detailed help for a specific tool")
        print("  run           Open notepad to paste/write a batch JSON, then execute it")
        print("  output        Print all accumulated tool outputs since last call")
        print("  history       Show last 10 output history entries (indexes 1-10)")
        print("  clear         Clear the accumulated output buffer")
        print("  exit / quit   Exit the client")
        print()
        print('Single tool usage:  <tool_name> {"param": "value", ...}')
        print('$ref syntax in batch/args:  "$ref <index> <variable_name>"')
        print('  index 1 = most recently completed tool output')
        print()


# ══════════════════════════════════════════════════════════════════════════════
# Batch execution
# ══════════════════════════════════════════════════════════════════════════════

async def execute_batch(batch: list[dict], session: ClientSession, display_buffer: list[str]) -> None:
    """
    Execute a list of tool call dicts sequentially.
    Each dict: {"tool": "tool_name", "args": {...}}
    $ref values in args are resolved immediately before each call.
    """
    for i, call in enumerate(batch):
        tool_name = call.get("tool", "").strip()
        raw_args  = call.get("args", {})

        if tool_name not in TOOLS:
            print(f"  [batch #{i+1}] Unknown tool: '{tool_name}' — skipping")
            continue

        schema = TOOLS[tool_name]

        # Resolve $ref inside the args dict
        raw_args = resolve_refs(raw_args)

        # Validate / coerce
        result_args: dict[str, Any] = {}
        error = None
        for name, meta in schema.items():
            if name in raw_args:
                val = raw_args[name]
                try:
                    result_args[name] = coerce(val, meta["type"], meta)
                except (ValueError, json.JSONDecodeError) as e:
                    error = f"Parameter '{name}': {e}"
                    break
            elif meta["required"]:
                error = f"Missing required parameter: '{name}' — {meta['desc']}"
                break

        if error:
            print(f"  [batch #{i+1}] {tool_name}: Error: {error} — skipping")
            continue

        print(f"  [batch #{i+1}] Running: {tool_name} ...", end=" ", flush=True)
        try:
            result  = await session.call_tool(tool_name, result_args)
            text    = format_result(result.content)
            push_output(tool_name, text)
            entry   = f"[{tool_name}]\n{textwrap.indent(text, '  ')}"
            display_buffer.append(entry)
            print("done")
        except Exception as e:
            print(f"error\n  Tool error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Notepad batch editor
# ══════════════════════════════════════════════════════════════════════════════

BATCH_TEMPLATE = """\
[
  {
    "tool": "tool_name_here",
    "args": {
      "param1": "value1"
    }
  },
  {
    "tool": "another_tool",
    "args": {
      "param1": "$ref 1 some_variable"
    }
  }
]
"""

def open_notepad_batch() -> list[dict] | None:
    """
    Open a temp file in notepad, wait for user to save & close,
    parse the JSON, return list of tool call dicts (or None on error/cancel).
    After close, reopen notepad with a blank template.
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    tmp.write(BATCH_TEMPLATE)
    tmp.flush()
    tmp.close()
    path = tmp.name

    print(f"Opening notepad: {path}")
    print("Paste your batch JSON, save the file, then close notepad.")

    try:
        subprocess.run(["notepad.exe", path], check=True)
    except FileNotFoundError:
        # Fallback: try start
        os.system(f'start notepad.exe "{path}"')
        input("Press Enter after you have saved and closed notepad...")
    except subprocess.CalledProcessError:
        pass

    # Read what the user saved
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except OSError as e:
        print(f"Could not read batch file: {e}")
        os.unlink(path)
        return None

    # Rewrite with blank template for next time
    with open(path, "w", encoding="utf-8") as f:
        f.write(BATCH_TEMPLATE)

    os.unlink(path)

    if not content or content == BATCH_TEMPLATE.strip():
        print("No batch submitted (file was unchanged).")
        return None

    try:
        batch = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in batch: {e}")
        return None

    if not isinstance(batch, list):
        print("Batch must be a JSON array [ ... ]")
        return None

    return batch


# ══════════════════════════════════════════════════════════════════════════════
# API integration
# ══════════════════════════════════════════════════════════════════════════════

def detect_provider(url: str) -> str:
    """Detect API provider from URL."""
    url_lower = url.lower()
    if "anthropic.com" in url_lower:
        return "anthropic"
    if "generativelanguage.googleapis.com" in url_lower or "google" in url_lower:
        return "google"
    # OpenAI-compatible: OpenAI, DeepSeek, Groq, OpenRouter, together.ai, etc.
    return "openai"


async def call_api(messages: list[dict], provider: str) -> str | None:
    """
    Call the configured AI API with the given messages.
    Returns the assistant's reply text, or None on error.
    """
    import urllib.request
    import urllib.error

    headers = {"Content-Type": "application/json"}

    if provider == "anthropic":
        headers["x-api-key"] = API_KEY
        headers["anthropic-version"] = "2023-06-01"
        # Anthropic uses system separately
        system_msgs = [m["content"] for m in messages if m["role"] == "system"]
        user_msgs   = [m for m in messages if m["role"] != "system"]
        payload = {
            "model":      API_MODEL,
            "max_tokens": 4096,
            "system":     "\n\n".join(system_msgs) if system_msgs else "",
            "messages":   user_msgs,
        }
    elif provider == "google":
        headers["x-goog-api-key"] = API_KEY
        # Convert to Google format
        contents = []
        for m in messages:
            if m["role"] == "system":
                contents.append({"role": "user",  "parts": [{"text": m["content"]}]})
                contents.append({"role": "model", "parts": [{"text": "Understood."}]})
            elif m["role"] == "assistant":
                contents.append({"role": "model", "parts": [{"text": m["content"]}]})
            else:
                contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        payload = {"contents": contents}
    else:
        # OpenAI-compatible
        headers["Authorization"] = f"Bearer {API_KEY}"
        payload = {
            "model":    API_MODEL,
            "messages": messages,
        }

    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(API_URL, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(f"  API error {e.code}: {body_text[:300]}")
        return None
    except Exception as e:
        print(f"  API request failed: {e}")
        return None

    try:
        if provider == "anthropic":
            return data["content"][0]["text"]
        if provider == "google":
            return data["candidates"][0]["content"]["parts"][0]["text"]
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        print(f"  Could not parse API response: {e}\n  Raw: {str(data)[:300]}")
        return None


def extract_batch_from_response(text: str) -> list[dict] | None:
    """
    Try to extract a JSON batch array from the AI's response text.
    Looks for ```json ... ``` block first, then bare [...] array.
    """
    # Try fenced code block
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try bare JSON array
    m = re.search(r"(\[.*\])", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    return None


def load_instructions() -> str:
    try:
        with open(INSTRUCTIONS_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# Main loop
# ══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    api_mode     = bool(API_KEY and API_URL and API_MODEL)
    provider     = detect_provider(API_URL) if api_mode else ""
    conv_history: list[dict] = []   # full conversation for API mode
    instructions_sent = False

    # Output display buffer (shown when user types `output`)
    display_buffer: list[str] = []
    output_has_new             = False  # True if a tool ran since last `output`

    server_params = StdioServerParameters(
        command="cmd.exe",
        args=["/c", MCP_BAT],
        env=None,
    )

    print("Connecting to Roblox Studio MCP server...")
    print(f"  launching: cmd.exe /c {MCP_BAT}")
    if api_mode:
        print(f"  API mode:  {provider} — {API_URL}")
    else:
        print("  Mode:      manual (no API key configured)")

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Connected.\n")
                print('Type "help" for available commands.\n')

                while True:
                    try:
                        prompt_str = "(api) > " if api_mode else "> "
                        line = input(prompt_str).strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\nExiting.")
                        break

                    if not line:
                        continue

                    low = line.lower()

                    # ── exit ──────────────────────────────────────────────
                    if low in ("exit", "quit"):
                        print("Exiting.")
                        break

                    # ── clear ─────────────────────────────────────────────
                    if low == "clear":
                        display_buffer.clear()
                        output_has_new = False
                        print("Output buffer cleared.")
                        continue

                    # ── history ───────────────────────────────────────────
                    if low == "history":
                        if not OUTPUT_HISTORY:
                            print("(no history)")
                        else:
                            print()
                            for idx, entry in enumerate(list(OUTPUT_HISTORY)[:10], start=1):
                                preview = entry["raw"][:80].replace("\n", " ")
                                print(f"  [{idx}] {entry['tool']}: {preview}")
                            print()
                        continue

                    # ── output ────────────────────────────────────────────
                    if low == "output":
                        if not output_has_new:
                            pass  # nothing new, do nothing
                        elif not display_buffer:
                            print("(no output accumulated)")
                        else:
                            print("\n" + "─" * 60)
                            for entry in display_buffer:
                                print(entry)
                                print()
                            print("─" * 60 + "\n")
                            display_buffer.clear()
                            output_has_new = False
                        continue

                    # ── help ──────────────────────────────────────────────
                    if low.startswith("help"):
                        parts = line.split(maxsplit=1)
                        print_help(parts[1].strip() if len(parts) > 1 else None)
                        continue

                    # ── run ───────────────────────────────────────────────
                    if low == "run":
                        if api_mode:
                            # In API mode, run still opens notepad for manual batch
                            batch = open_notepad_batch()
                        else:
                            batch = open_notepad_batch()

                        if batch:
                            print(f"Executing batch of {len(batch)} tool call(s)...")
                            await execute_batch(batch, session, display_buffer)
                            output_has_new = True
                            print("Batch complete. Type 'output' to see results.")
                        continue

                    # ── single tool call ──────────────────────────────────
                    parts     = line.split(maxsplit=1)
                    tool_name = parts[0].lower()
                    raw_args  = parts[1] if len(parts) > 1 else ""

                    if tool_name in TOOLS:
                        schema = TOOLS[tool_name]
                        args, err = parse_args(raw_args, schema)
                        if err:
                            print(f"Error: {err}")
                            continue
                        try:
                            result = await session.call_tool(tool_name, args)
                            text   = format_result(result.content)
                            push_output(tool_name, text)
                            entry  = f"[{tool_name}]\n{textwrap.indent(text, '  ')}"
                            display_buffer.append(entry)
                            output_has_new = True
                        except Exception as e:
                            print(f"Tool error: {e}")
                        continue

                    # ── API mode: natural language query ──────────────────
                    if api_mode:
                        # On first message, prepend instructions as system prompt
                        if not instructions_sent:
                            instructions = load_instructions()
                            if instructions:
                                conv_history.insert(0, {
                                    "role":    "system",
                                    "content": instructions,
                                })
                            instructions_sent = True

                        conv_history.append({"role": "user", "content": line})
                        print("Querying AI...", flush=True)

                        reply = await call_api(conv_history, provider)
                        if reply is None:
                            continue

                        conv_history.append({"role": "assistant", "content": reply})

                        # Try to extract and run a batch from the response
                        batch = extract_batch_from_response(reply)
                        if batch:
                            # Print the non-JSON part of the reply as context
                            non_json = re.sub(r"```(?:json)?\s*\[.*?\]\s*```", "", reply, flags=re.DOTALL).strip()
                            if non_json:
                                print(f"\nAI: {non_json}\n")
                            print(f"Executing AI batch of {len(batch)} tool call(s)...")
                            await execute_batch(batch, session, display_buffer)
                            output_has_new = True

                            # Add tool results to conversation history
                            results_text = "\n\n".join(
                                f"[{e['tool']}]: {e['raw']}"
                                for e in list(OUTPUT_HISTORY)[:len(batch)]
                            )
                            conv_history.append({
                                "role":    "user",
                                "content": f"Tool results:\n{results_text}",
                            })

                            print("Batch complete. Type 'output' to see results.")
                        else:
                            # Plain text response
                            print(f"\nAI: {reply}\n")
                        continue

                    # ── unknown command ───────────────────────────────────
                    print(f"Unknown command: '{tool_name}'. Type 'help' for a list.")

    except FileNotFoundError:
        print(f"\nError: Could not find mcp.bat at:\n  {MCP_BAT}")
        print("Make sure Roblox Studio is installed and the MCP server is configured.")
        sys.exit(1)
    except Exception as e:
        print(f"\nConnection error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
