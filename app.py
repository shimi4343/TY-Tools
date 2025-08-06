"""
Streamlit WebApp: Script Writer with yt-dlp
Author: Modified for yt-dlp
Date: 2025-07-15 (rev-13)

Change log (rev-13)
------------------
* youtube-transcript-api を yt-dlp に置き換え
* Streamlit Community Cloud での動作を最適化
* エラーハンドリングの改善
"""

from __future__ import annotations

import os
import re
import textwrap
from typing import List, Dict, Any

import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
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

load_dotenv()

# Streamlit Secretsからも読み込み可能に
if "ANTHROPIC_API_KEY" in st.secrets:
    api_key = st.secrets["ANTHROPIC_API_KEY"]
else:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")

client = anthropic.Anthropic(api_key=api_key)
if not client.api_key:
    st.error("ANTHROPIC_API_KEY is not set. Please add it to your .env or Streamlit secrets.")
    st.stop()


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def extract_video_id(url: str) -> str:
    """YouTube URLから動画IDを抽出"""
    for pattern in (r"(?<=v=)[A-Za-z0-9_-]{11}", r"youtu\.be/([A-Za-z0-9_-]{11})", r"embed/([A-Za-z0-9_-]{11})", r"shorts/([A-Za-z0-9_-]{11})"):
        if (m := re.search(pattern, url)):
            return m.group(1) if m.groups() else m.group(0)
    return ""






@st.cache_data(show_spinner=False, ttl=3600)  # 1時間キャッシュ
def fetch_english_transcript(video_id: str) -> tuple[str, str]:
    """
    youtube-transcript-apiを使って英語字幕を取得
    Returns: (transcript_text, error_message)
    """
    try:
        # 手動英語字幕を優先的に取得
        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        except:
            # 手動字幕がない場合は自動生成英語字幕を取得
            try:
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
            except:
                # 英語がない場合のエラー
                return "", "英語字幕が見つかりませんでした。この動画には英語字幕が設定されていない可能性があります。"
        
        # 字幕テキストを結合
        transcript_text = ' '.join([entry['text'] for entry in transcript])
        
        if not transcript_text:
            return "", "字幕データが空でした。"
        
        return transcript_text, ""
        
    except Exception as e:
        from youtube_transcript_api._errors import TranscriptsDisabled, VideoUnavailable, NoTranscriptFound
        
        if isinstance(e, TranscriptsDisabled):
            return "", "この動画では字幕が無効化されています。"
        elif isinstance(e, VideoUnavailable):
            return "", "動画が利用できません。非公開または削除されている可能性があります。"
        elif isinstance(e, NoTranscriptFound):
            return "", "英語字幕が見つかりませんでした。この動画には英語字幕が設定されていない可能性があります。"
        else:
            return "", f"予期しないエラーが発生しました: {type(e).__name__}: {str(e)}"


def translate_to_japanese(text: str) -> str:
    """英語テキストを日本語に翻訳"""
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



# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
CSS = """
<style>
section.main > div {padding-top: 1rem;}
textarea {
    font-size: 0.85rem;
    /* スクロールバーを常に表示 */
    overflow-y: scroll !important;
}
[data-testid="stTextArea"] label {font-weight: 600;}
.stAlert {margin-top: 1rem;}

/* テキストエリアのスクロール改善 */
.stTextArea > div > div > textarea {
    overflow-y: auto !important;
    max-height: none !important;
}
</style>
"""

st.set_page_config(page_title="Script Translator", layout="wide", page_icon="🎬")
st.markdown(CSS, unsafe_allow_html=True)
st.title("🎬 Script Translator")

# Session init
for k, v in {
    "eng_text": "",
    "jp_text": "",
    "jp_ta": "",
    "video_id": "",
    "input_method": "YouTube URL",
}.items():
    st.session_state.setdefault(k, v)


# 入力方法の選択
st.session_state["input_method"] = st.radio(
    "入力方法を選択",
    ["YouTube URL", "英語字幕を直接入力"],
    index=0 if st.session_state["input_method"] == "YouTube URL" else 1,
    horizontal=True
)

# Input controls
if st.session_state["input_method"] == "YouTube URL":
    url = st.text_input("YouTube URLを入力してください：", key="url_input")
    st.info("💡 字幕の取得に失敗する場合は、「英語字幕を直接入力」オプションをお試しください。")
    
    cols_btn = st.columns(2)
    fetch_clicked = cols_btn[0].button("🚀 Fetch & Translate")
    clear_clicked = cols_btn[1].button("✂︎ Clear")
else:
    eng_text_input = st.text_area(
        "英語字幕を貼り付けてください：",
        height=200,
        placeholder="YouTubeの字幕をここに貼り付けてください...",
        key="manual_eng_input"
    )
    st.caption("YouTubeで動画を開き、字幕ボタン → 文字起こしを表示 → 英語テキストをコピーしてください。")
    
    cols_btn = st.columns(2)
    fetch_clicked = cols_btn[0].button("🚀 Translate")
    clear_clicked = cols_btn[1].button("✂︎ Clear")

if clear_clicked:
    for key in ("eng_text", "jp_text", "jp_ta", "video_id"):
        st.session_state[key] = ""
    _rerun()

# Processing
if fetch_clicked:
    if st.session_state["input_method"] == "YouTube URL" and url:
        vid = extract_video_id(url)
        if not vid:
            st.error("動画 ID を URL から抽出できませんでした。URL を確認してください。")
            st.stop()

        with st.spinner("英語字幕を取得中…"):
            eng, error_msg = fetch_english_transcript(vid)
        
        if error_msg:
            st.error(f"❌ {error_msg}")
            st.info("💡 「英語字幕を直接入力」オプションを使用してください。")
            st.stop()
        
        if not eng:
            st.error("英語字幕が見つかりませんでした。")
            st.stop()
        
        st.session_state["video_id"] = vid
    
    elif st.session_state["input_method"] == "英語字幕を直接入力" and eng_text_input:
        eng = eng_text_input.strip()
        if not eng:
            st.error("英語字幕を入力してください。")
            st.stop()
    else:
        st.error("URLまたは英語字幕を入力してください。")
        st.stop()

    with st.spinner("日本語に翻訳中… (Claude Sonnet 4)"):
        jp = translate_to_japanese(eng)

    st.session_state.update(
        {
            "eng_text": eng,
            "jp_text": jp,
            "jp_ta": jp,
        }
    )
    
    if st.session_state["input_method"] == "英語字幕を直接入力":
        st.session_state["video_id"] = ""
    
    _rerun()

# Display outputs
if st.session_state["eng_text"]:
    # テキストの長さに基づいて動的に高さを計算
    text_length = max(
        len(st.session_state["eng_text"]),
        len(st.session_state["jp_ta"])
    )
    
    # 文字数に応じて高さを調整（100文字あたり約20px）
    dynamic_height = min(max(500, text_length // 100 * 20), 1000)
    
    col_eng, col_jp = st.columns(2)

    with col_eng:
        st.text_area("English Transcript", value=st.session_state["eng_text"], height=dynamic_height, disabled=True)
    with col_jp:
        st.text_area("Japanese Translation (editable)", value=st.session_state["jp_ta"], height=dynamic_height, key="jp_edit")
        st.session_state["jp_ta"] = st.session_state["jp_edit"]
        
        # 文字数を表示とコピーボタンを横並びで配置
        col_count, col_copy = st.columns([1, 2])
        with col_count:
            jp_char_count = len(st.session_state["jp_ta"])
            st.caption(f"文字数: {jp_char_count:,}")
        with col_copy:
            if st.button("📋 翻訳結果をコピー", key="copy_jp"):
                st.session_state["copy_text"] = st.session_state["jp_ta"]
                st.success("翻訳結果をクリップボードにコピーしました！")
        
        # JavaScriptでコピー機能を実装
        if "copy_text" in st.session_state and st.session_state["copy_text"]:
            st.markdown(
                f"""
                <script>
                navigator.clipboard.writeText(`{st.session_state['copy_text'].replace('`', '\\`')}`);
                </script>
                """,
                unsafe_allow_html=True
            )
            del st.session_state["copy_text"]

    # Video embed under columns
    if st.session_state["video_id"]:
        st.markdown("---")
        st.video(f"https://www.youtube.com/watch?v={st.session_state['video_id']}")

# Footer with debug info (開発時のみ表示)
with st.expander("🔧 Debug Info", expanded=False):
    try:
        import youtube_transcript_api
        version = getattr(youtube_transcript_api, '__version__', 'unknown')
        st.caption(f"youtube-transcript-api version: {version}")
    except:
        st.caption("youtube-transcript-api: installed")
    st.caption(f"Python version: {os.sys.version}")
    st.caption(f"Streamlit version: {st.__version__}")