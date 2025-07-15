"""
Streamlit WebApp: Script Writer
Author: ChatGPT (OpenAI o3)
Date: 2025-07-15 (rev-12)

Change log (rev-12)
------------------
* **Prompt Sent** 表示を削除（不要とのリクエスト）
* 出力レイアウトを **3 カラム同時表示**（英語 / 日本語 / 生成スクリプト）に変更。
* YouTube 埋め込みは 3 カラムの下に据え置き。
"""

from __future__ import annotations

import os
import re
import textwrap
from pathlib import Path
from typing import List

import streamlit as st
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    CouldNotRetrieveTranscript,
)
import anthropic
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Helper: Streamlit rerun (new/old API 対応)
# ---------------------------------------------------------------------------

def _rerun() -> None:
    (st.rerun if hasattr(st, "rerun") else st.experimental_rerun)()  # type: ignore[arg-type]

# ---------------------------------------------------------------------------
# Config & init
# ---------------------------------------------------------------------------
PROMPT_PATH = Path(__file__).with_name("prompt.md")
DEFAULT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
if not client.api_key:
    st.error("ANTHROPIC_API_KEY is not set. Please add it to your .env or Streamlit secrets.")
    st.stop()

# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def extract_video_id(url: str) -> str:
    for pattern in (r"(?<=v=)[A-Za-z0-9_-]{11}", r"youtu\.be/([A-Za-z0-9_-]{11})", r"embed/([A-Za-z0-9_-]{11})"):
        if (m := re.search(pattern, url)):
            return m.group(1) if m.groups() else m.group(0)
    return ""


@st.cache_data(show_spinner=False)
def fetch_english_transcript(video_id: str) -> str:
    try:
        seg: List[dict] = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        return " ".join(s.get("text", "") for s in seg)
    except (NoTranscriptFound, TranscriptsDisabled, CouldNotRetrieveTranscript):
        return ""


def translate_to_japanese(text: str) -> str:
    if not text:
        return ""
    jp_parts: list[str] = []
    for chunk in textwrap.wrap(text, 6000):
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            temperature=0.1,
            messages=[{"role": "user", "content": "以下の英文を自然な日本語（敬体、です・ます調）に翻訳してください。原文の改行を維持してください。\n\n" + chunk}],
        )
        jp_parts.append(resp.content[0].text.strip())
    return "\n\n".join(jp_parts)


def generate_script(template: str, eng_text: str) -> str:
    prompt = template.replace("{{ Theme }}", eng_text)
    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()

# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
CSS = """
<style>
section.main > div {padding-top: 1rem;}
textarea {font-size: 0.85rem;}
[data-testid="stTextArea"] label {font-weight: 600;}
</style>
"""

st.set_page_config(page_title="Script Writer", layout="wide", page_icon="🎬")
st.markdown(CSS, unsafe_allow_html=True)
st.title("🎬 Script Writer")

# Session init
for k, v in {
    "eng_text": "",
    "jp_text": "",
    "jp_ta": "",
    "script_text": "",
    "script_ta": "",
    "prompt_template": DEFAULT_TEMPLATE,
    "video_id": "",
}.items():
    st.session_state.setdefault(k, v)

# Prompt editor
with st.expander("📝 Claude プロンプトテンプレート（編集可）", expanded=False):
    new_template = st.text_area(
        "Prompt Template",
        value=st.session_state["prompt_template"],
        height=300,
        key="prompt_template_ta",
    )
    st.session_state["prompt_template"] = new_template
    st.caption("`{{ Theme }}` が英語スクリプトに置換されて送信されます。")

# Input controls
url = st.text_input("YouTube URLを入力してください：", key="url_input")
cols_btn = st.columns(2)
fetch_clicked = cols_btn[0].button("🚀 Fetch / 生成")
clear_clicked = cols_btn[1].button("✂︎ Clear")

if clear_clicked:
    for key in ("eng_text", "jp_text", "jp_ta", "script_text", "script_ta", "video_id"):
        st.session_state[key] = ""
    _rerun()

# Processing
if fetch_clicked and url:
    vid = extract_video_id(url)
    if not vid:
        st.error("動画 ID を URL から抽出できませんでした。URL を確認してください。")
        st.stop()

    with st.spinner("英語スクリプトを取得中…"):
        eng = fetch_english_transcript(vid)
    if not eng:
        st.error("英語字幕が見つかりませんでした。")
        st.stop()

    with st.spinner("日本語に翻訳中… (Claude Sonnet 4)"):
        jp = translate_to_japanese(eng)

    with st.spinner("ショート動画台本を生成中…"):
        script = generate_script(st.session_state["prompt_template"], eng)

    st.session_state.update(
        {
            "eng_text": eng,
            "jp_text": jp,
            "jp_ta": jp,
            "script_text": script,
            "script_ta": script,
            "video_id": vid,
        }
    )
    _rerun()

# Display outputs
if st.session_state["eng_text"]:
    col_eng, col_jp, col_sc = st.columns(3)

    with col_eng:
        st.text_area("English Transcript", value=st.session_state["eng_text"], height=350, disabled=True)
    with col_jp:
        st.session_state["jp_ta"] = st.text_area("Japanese Translation (editable)", value=st.session_state["jp_ta"], height=350)
    with col_sc:
        st.session_state["script_ta"] = st.text_area("Shorts Script (editable)", value=st.session_state["script_ta"], height=350)

    # Video embed under columns
    if st.session_state["video_id"]:
        st.markdown("---")
        st.video(f"https://www.youtube.com/watch?v={st.session_state['video_id']}")
