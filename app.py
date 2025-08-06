"""
Streamlit WebApp: Script Writer with yt-dlp (Fixed)
Author: Modified for yt-dlp
Date: 2025-01-16 (fixed version)

主な修正点:
- yt-dlpのオプション設定を修正
- 字幕取得ロジックを改善
- デバッグ情報の追加
"""

from __future__ import annotations

import os
import re
import textwrap
import json
from typing import List, Optional, Dict, Any
import tempfile

import streamlit as st
import yt_dlp
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
# yt-dlp configuration (修正版)
# ---------------------------------------------------------------------------

def get_ydl_opts() -> Dict[str, Any]:
    """yt-dlpのオプションを返す（修正版）"""
    temp_dir = tempfile.gettempdir()
    
    return {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        # 字幕関連のオプションを簡潔に
        'subtitleslangs': ['en', 'en-US', 'en-GB', 'a.en'],  # 'a.en'は自動生成英語字幕
        'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
        'cachedir': temp_dir,
        'socket_timeout': 30,
        'retries': 3,
        'fragment_retries': 3,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'no_color': True,
        # 自動生成字幕を明示的に有効化
        'writeautomaticsub': False,  # 実際にファイルに書き込まない
        'allsubtitles': False,
        'writesubtitles': False,
    }

# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def extract_video_id(url: str) -> str:
    """YouTube URLから動画IDを抽出"""
    for pattern in (r"(?<=v=)[A-Za-z0-9_-]{11}", r"youtu\.be/([A-Za-z0-9_-]{11})", r"embed/([A-Za-z0-9_-]{11})", r"shorts/([A-Za-z0-9_-]{11})"):
        if (m := re.search(pattern, url)):
            return m.group(1) if m.groups() else m.group(0)
    return ""


def parse_subtitle_json(subtitle_data: List[Dict[str, Any]]) -> str:
    """JSON3形式の字幕データをテキストに変換"""
    text_parts = []
    for entry in subtitle_data:
        if 'segs' in entry:
            # セグメントがある場合（通常の字幕）
            segment_text = ' '.join(seg.get('utf8', '') for seg in entry['segs'] if seg.get('utf8'))
            if segment_text.strip():
                text_parts.append(segment_text.strip())
        elif 'text' in entry:
            # 直接テキストがある場合
            if entry['text'].strip():
                text_parts.append(entry['text'].strip())
    
    return ' '.join(text_parts)


@st.cache_data(show_spinner=False, ttl=3600)  # 1時間キャッシュ
def fetch_english_transcript_ytdlp(video_id: str) -> tuple[str, str, str]:
    """
    yt-dlpを使って字幕を取得（修正版）
    Returns: (transcript_text, error_message, language_code)
    """
    try:
        ydl_opts = get_ydl_opts()
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 動画情報を取得
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            if not info:
                return "", "動画情報を取得できませんでした。", ""
            
            # デバッグ情報を取得
            subtitles = info.get('subtitles', {})
            automatic_captions = info.get('automatic_captions', {})
            
            
            # 字幕を探す（優先順位を改善）
            subtitle_url = None
            found_lang = None
            
            # 1. 英語の自動生成字幕を最優先で確認（より広範囲の言語コード）
            english_codes = ['en', 'en-US', 'en-GB', 'en-CA', 'en-AU', 'en-NZ', 'en-IN', 'a.en']
            
            for lang in english_codes:
                if lang in automatic_captions:
                    # json3形式を優先、なければ他の形式も試す
                    for sub in automatic_captions[lang]:
                        if sub.get('ext') in ['json3', 'srv3', 'srv2', 'srv1', 'vtt', 'ttml']:
                            subtitle_url = sub['url']
                            found_lang = lang
                            st.success(f"✅ 自動生成字幕を発見: {lang} ({sub.get('ext')}形式)")
                            break
                    if subtitle_url:
                        break
            
            # 2. 英語の手動字幕を確認
            if not subtitle_url:
                for lang in english_codes:
                    if lang in subtitles:
                        for sub in subtitles[lang]:
                            if sub.get('ext') in ['json3', 'srv3', 'srv2', 'srv1', 'vtt', 'ttml']:
                                subtitle_url = sub['url']
                                found_lang = lang
                                st.success(f"✅ 手動字幕を発見: {lang} ({sub.get('ext')}形式)")
                                break
                        if subtitle_url:
                            break
            
            # 3. 他の言語の自動生成字幕を確認（英語がない場合）
            if not subtitle_url and automatic_captions:
                # まず一般的な言語を優先的に確認
                priority_langs = ['ja', 'es', 'fr', 'de', 'it', 'pt', 'ko', 'zh', 'zh-CN', 'zh-TW']
                for lang in priority_langs:
                    if lang in automatic_captions:
                        for sub in automatic_captions[lang]:
                            if sub.get('ext') in ['json3', 'srv3', 'srv2', 'srv1', 'vtt', 'ttml']:
                                subtitle_url = sub['url']
                                found_lang = lang
                                st.warning(f"⚠️ 英語字幕が見つからないため、{lang}言語の字幕を使用します")
                                break
                        if subtitle_url:
                            break
            
            if not subtitle_url:
                # デバッグ情報を詳しく表示
                error_msg = "字幕が見つかりませんでした。\n\n"
                if automatic_captions:
                    error_msg += f"利用可能な自動生成字幕の言語: {', '.join(automatic_captions.keys())}\n"
                if subtitles:
                    error_msg += f"利用可能な手動字幕の言語: {', '.join(subtitles.keys())}\n"
                if not automatic_captions and not subtitles:
                    error_msg += "この動画には字幕が設定されていません。"
                return "", error_msg, ""
            
            # 字幕データをダウンロード
            import urllib.request
            with urllib.request.urlopen(subtitle_url) as response:
                subtitle_content = response.read().decode('utf-8')
            
            # フォーマットに応じて解析
            if subtitle_url.endswith('.json3') or 'json3' in subtitle_url:
                subtitle_json = json.loads(subtitle_content)
                if 'events' in subtitle_json:
                    transcript_text = parse_subtitle_json(subtitle_json['events'])
                else:
                    transcript_text = parse_subtitle_json(subtitle_json)
            elif subtitle_url.endswith('.vtt') or 'vtt' in subtitle_url:
                # VTT形式の場合の簡易パース
                lines = subtitle_content.split('\n')
                transcript_text = ' '.join(
                    line.strip() for line in lines 
                    if line.strip() and not line.startswith('WEBVTT') 
                    and not '-->' in line and not line.strip().isdigit()
                )
            else:
                # その他の形式（srv1, srv2, srv3, ttml）
                # XMLベースの形式の場合、簡易的にテキスト部分を抽出
                import re
                text_pattern = r'>([^<]+)<'
                matches = re.findall(text_pattern, subtitle_content)
                transcript_text = ' '.join(matches)
            
            if not transcript_text:
                return "", "字幕データの解析に失敗しました。", ""
            
            return transcript_text, "", found_lang or "en"
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "Video unavailable" in error_msg:
            return "", "動画が利用できません。非公開または削除されている可能性があります。", ""
        elif "Sign in to confirm your age" in error_msg:
            return "", "年齢制限のある動画です。字幕を取得できません。", ""
        else:
            return "", f"ダウンロードエラー: {error_msg}", ""
    except json.JSONDecodeError:
        return "", "字幕データの形式が正しくありません。", ""
    except Exception as e:
        return "", f"予期しないエラーが発生しました: {type(e).__name__}: {str(e)}", ""


def translate_to_japanese(text: str, source_lang: str = "en") -> str:
    """テキストを日本語に翻訳"""
    if not text:
        return ""
    
    # 言語に応じてプロンプトを調整
    if source_lang.startswith('en'):
        prompt_prefix = "以下の英文を自然な日本語（敬体、です・ます調）に翻訳してください。原文の改行を維持してください。\n\n"
    else:
        prompt_prefix = f"以下のテキスト（言語コード: {source_lang}）を自然な日本語（敬体、です・ます調）に翻訳してください。原文の改行を維持してください。\n\n"
    
    jp_parts: list[str] = []
    for chunk in textwrap.wrap(text, 6000):
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt_prefix + chunk}],
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

        with st.spinner("字幕を取得中…"):
            eng, error_msg, source_lang = fetch_english_transcript_ytdlp(vid)
        
        if error_msg:
            st.error(f"❌ {error_msg}")
            st.info("💡 「英語字幕を直接入力」オプションを使用してください。")
            st.stop()
        
        if not eng:
            st.error("字幕が見つかりませんでした。")
            st.stop()
        
        st.session_state["video_id"] = vid
        
        # 取得した字幕の言語を表示
        if source_lang and not source_lang.startswith("en"):
            st.info(f"💡 英語字幕が見つからなかったため、{source_lang}言語の字幕を取得しました。")
    
    elif st.session_state["input_method"] == "英語字幕を直接入力" and eng_text_input:
        eng = eng_text_input.strip()
        source_lang = "en"  # 直接入力の場合は英語として扱う
        if not eng:
            st.error("英語字幕を入力してください。")
            st.stop()
    else:
        st.error("URLまたは英語字幕を入力してください。")
        st.stop()

    with st.spinner("日本語に翻訳中… (Claude Sonnet 4)"):
        jp = translate_to_japanese(eng, source_lang)

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
        st.text_area("Original Transcript", value=st.session_state["eng_text"], height=dynamic_height, disabled=True)
    with col_jp:
        st.text_area("Japanese Translation (editable)", value=st.session_state["jp_ta"], height=dynamic_height, key="jp_edit")
        st.session_state["jp_ta"] = st.session_state["jp_edit"]
        
        # コピーボタンを追加
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
    st.caption(f"yt-dlp version: {yt_dlp.version.__version__}")
    st.caption(f"Python version: {os.sys.version}")
    st.caption(f"Streamlit version: {st.__version__}")
    
    # yt-dlpのバージョンが古い場合の警告
    if hasattr(yt_dlp.version, '__version__'):
        import packaging.version
        if packaging.version.parse(yt_dlp.version.__version__) < packaging.version.parse("2024.0.0"):
            st.warning("⚠️ yt-dlpのバージョンが古い可能性があります。最新版へのアップデートを推奨します: `pip install -U yt-dlp`")