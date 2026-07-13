#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "wcwidth>=0.2.0",
# ]
# ///
"""UserPromptSubmit hook — topic extraction + prompt counting.

Reads hook stdin JSON: {session_id, data: {prompt, timestamp}}
prompt can be a string OR an array of content blocks (multimodal).
Extracts topic from first 3 significant words, appends to state.json topic_history.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Add lib/ to import path
LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from state import load_state, save_state

# Words to skip when extracting topics
STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "again", "further", "then", "once",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "they", "them", "their", "this", "that", "these", "those",
    "and", "but", "or", "nor", "not", "no", "so", "if", "when",
    "can", "could", "will", "would", "should", "shall", "may", "might",
    "do", "does", "did", "done", "have", "has", "had", "having",
    "what", "which", "who", "whom", "how", "where", "why",
    "all", "each", "every", "both", "few", "more", "most", "some", "any",
    "please", "also", "just", "now", "here", "there", "very", "really",
    "about", "up", "out", "like", "make", "get", "go", "know", "think",
})

MAX_TOPIC_HISTORY = 50
TOPIC_WORD_COUNT = 3
TITLE_WORD_COUNT = 5


def extract_text(prompt) -> str:
    """Extract plain text from prompt (string or content block array)."""
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, list):
        # Array of content blocks: [{type: "text", text: "..."}, ...]
        parts = []
        for block in prompt:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return str(prompt)


def extract_topic(text: str) -> str:
    """Extract topic from text: first N significant words, lowercase."""
    words = text.lower().split()
    significant = []
    for word in words:
        # Strip punctuation
        clean = word.strip(".,!?;:'\"()[]{}/@#$%^&*-_=+<>~`")
        if not clean or clean in STOPWORDS or len(clean) < 2:
            continue
        significant.append(clean)
        if len(significant) >= TOPIC_WORD_COUNT:
            break
    return " ".join(significant) if significant else ""


def extract_title(text: str) -> str:
    """Extract session title from text: first N significant words, title case."""
    words = text.lower().split()
    significant = []
    for word in words:
        clean = word.strip(".,!?;:'\"()[]{}/@#$%^&*-_=+<>~`")
        if not clean or clean in STOPWORDS or len(clean) < 2:
            continue
        significant.append(clean)
        if len(significant) >= TITLE_WORD_COUNT:
            break
    if not significant:
        return ""
    return " ".join(significant).title()


def main() -> None:
    # Read hook stdin
    try:
        raw = sys.stdin.read()
        hook_data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, Exception):
        hook_data = {}

    session_id = hook_data.get("session_id", "")
    data = hook_data.get("data", {})
    prompt = data.get("prompt", "")

    # Extract text and topic
    text = extract_text(prompt)
    topic = extract_topic(text)

    if not topic:
        return

    # Load and update state
    state = load_state()

    # Infer session title from first prompt
    prompt_count = state.get("prompt_count", 0)
    if prompt_count == 0 and text:
        title = extract_title(text)
        if title:
            state["session_title"] = title
            # Update SQLite session title
            conn = None
            try:
                from db import get_connection, ensure_schema, update_session_title
                conn = get_connection()
                ensure_schema(conn)
                update_session_title(conn, session_id, title)
            except Exception as e:
                sys.stderr.write(f"statusline: user_prompt title update: {e}\n")
            finally:
                if conn:
                    conn.close()

    # Only add if different from last topic
    history = state.get("topic_history", [])
    if not history or history[-1] != topic:
        history.append(topic)
        # Cap at MAX_TOPIC_HISTORY
        if len(history) > MAX_TOPIC_HISTORY:
            history = history[-MAX_TOPIC_HISTORY:]
        state["topic_history"] = history

    # Increment prompt count
    state["prompt_count"] = state.get("prompt_count", 0) + 1

    # Append to grid (per-session file)
    import time as _time
    try:
        from grid import Cell
        from grid_io import load_grid, save_grid
        from grid_mapper import map_event, get_weight
        emoji, key = map_event("UserPromptSubmit")
        weight = get_weight(key)
        grid = load_grid(session_id)
        grid.append(Cell(emoji=emoji, key=key, weight=weight, ts=_time.time()))
        save_grid(session_id, grid)
    except Exception as e:
        sys.stderr.write(f"statusline: user_prompt grid append: {e}\n")

    # Update session last_prompt timestamp
    sessions = state.get("sessions", {})
    if session_id in sessions and isinstance(sessions[session_id], dict):
        sessions[session_id]["last_prompt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    # Save state (best-effort)
    try:
        save_state(state)
    except Exception as e:
        sys.stderr.write(f"statusline: user_prompt save_state: {e}\n")


if __name__ == "__main__":
    main()
