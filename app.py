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
import subprocess
import sys
import glob
import shutil
import platform
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

# 環境変数から読み込み（Railway環境対応）
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
# Video Downloader Functions
# ---------------------------------------------------------------------------

def validate_time_format(time_str):
    """時間フォーマットを検証（00:00, 00:12, 01:22:33, 0000, 000010形式）"""
    # MM:SS または HH:MM:SS 形式
    colon_pattern = r'^\d{1,2}:\d{2}(:\d{2})?$'
    # MMSS または HHMMSS 形式（4桁または6桁）
    digit_pattern = r'^\d{4}$|^\d{6}$'
    
    return re.match(colon_pattern, time_str) is not None or re.match(digit_pattern, time_str) is not None

def normalize_time_format(time_str):
    """時間フォーマットを正規化（4桁・6桁をMM:SS・HH:MM:SS形式に変換）"""
    if re.match(r'^\d{4}$', time_str):
        # 4桁の場合：MMSS -> MM:SS
        return f"{time_str[:2]}:{time_str[2:]}"
    elif re.match(r'^\d{6}$', time_str):
        # 6桁の場合：HHMMSS -> HH:MM:SS
        return f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"
    else:
        # すでに正しい形式の場合はそのまま返す
        return time_str

def validate_youtube_url_downloader(url):
    """YouTubeのURLを検証"""
    youtube_patterns = [
        r'https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'https?://youtu\.be/[\w-]+',
        r'https?://(?:www\.)?youtube\.com/embed/[\w-]+',
        r'https?://(?:www\.)?youtube\.com/shorts/[\w-]+'
    ]
    return any(re.match(pattern, url) for pattern in youtube_patterns)

def get_unique_filename(base_path):
    """既存ファイルと重複しない一意のファイル名を生成"""
    if not os.path.exists(base_path):
        return base_path
    
    # ファイル名と拡張子を分離
    name, ext = os.path.splitext(base_path)
    counter = 2
    
    while os.path.exists(f"{name}_V{counter}{ext}"):
        counter += 1
    
    return f"{name}_V{counter}{ext}"

def format_command_display(cmd, download_sections, youtube_url):
    """表示用にコマンドの引数を引用符で囲む"""
    cmd_display = []
    for arg in cmd:
        if arg == "best[height<=1080]/best":
            cmd_display.append(f'"{arg}"')
        elif arg == "mp4":
            cmd_display.append(f'"{arg}"')
        elif "%(title)s_%(height)s_%(fps)s_%(vcodec.:4)s_(%(id)s)" in arg:
            cmd_display.append(f'"{arg}"')
        elif arg == download_sections:
            cmd_display.append(f'"{arg}"')
        elif arg == youtube_url:
            cmd_display.append(f'"{arg}"')
        else:
            cmd_display.append(arg)
    return " ".join(cmd_display)

def cleanup_server_file():
    """サーバー上のファイルとセッション状態をクリーンアップ"""
    if st.session_state.downloaded_file_path and os.path.exists(st.session_state.downloaded_file_path):
        try:
            os.remove(st.session_state.downloaded_file_path)
        except Exception:
            pass  # エラーは無視
    
    # セッション状態をクリア
    st.session_state.downloaded_file_path = None
    st.session_state.downloaded_file_data = None
    st.session_state.downloaded_file_name = None

def cleanup_bulk_files():
    """バルクダウンロードファイルとセッション状態をクリーンアップ"""
    for file_info in st.session_state.bulk_downloaded_files:
        if file_info.get('path') and os.path.exists(file_info['path']):
            try:
                os.remove(file_info['path'])
            except Exception:
                pass
    
    # セッション状態をクリア
    st.session_state.bulk_downloaded_files = []
    st.session_state.bulk_download_progress = {}
    st.session_state.bulk_download_errors = {}

def download_single_video_bulk(url, time_settings, progress_placeholder, error_placeholder, success_placeholder):
    """バルクダウンロード用の単一動画ダウンロード処理"""
    try:
        progress_placeholder.info(f"🔄 ダウンロード中: {url[:50]}...")
        
        # コマンドを構築
        cmd = [
            "yt-dlp"
        ]
        
        # クラウド環境の検出
        is_cloud_environment = False
        try:
            is_cloud_environment = (
                "STREAMLIT_SHARING" in os.environ or 
                "streamlit" in os.environ.get("HOME", "").lower() or
                "appuser" in os.environ.get("HOME", "").lower() or
                os.path.exists("/home/appuser") or
                "RAILWAY_ENVIRONMENT" in os.environ or
                "PORT" in os.environ
            )
        except Exception:
            pass
        
        # ローカル環境でのみクッキーオプションを追加
        if not is_cloud_environment:
            try:
                cmd.extend(["--cookies-from-browser", "chrome"])
            except Exception:
                pass
        
        # 時間指定がある場合
        if time_settings:
            download_sections = f"*{time_settings['start']}-{time_settings['end']}"
            cmd.extend([
                "--download-sections", download_sections,
                "--force-keyframes-at-cuts"
            ])
        
        # 一時ディレクトリの設定
        temp_dir = tempfile.mkdtemp()
        cmd.extend([
            "-f", "best[height<=1080]/best",
            "--merge-output-format", "mp4",
            "-o", os.path.join(temp_dir, "%(title)s_%(height)s_%(fps)s_%(vcodec.:4)s_(%(id)s).%(ext)s"),
            url
        ])
        
        # ダウンロード実行
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        
        # ダウンロードされたファイルを確認
        temp_files = glob.glob(os.path.join(temp_dir, "*.mp4"))
        if temp_files:
            temp_file = temp_files[0]
            original_name = os.path.basename(temp_file)
            final_path = get_unique_filename(original_name)
            shutil.move(temp_file, final_path)
            
            # ファイルデータを読み込み
            with open(final_path, "rb") as f:
                file_data = f.read()
            
            # 一時ディレクトリをクリーンアップ
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            success_placeholder.success(f"✅ 完了: {original_name}")
            progress_placeholder.empty()
            
            return {
                'url': url,
                'filename': os.path.basename(final_path),
                'path': final_path,
                'data': file_data,
                'success': True
            }
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)
            error_msg = "ファイルのダウンロードに失敗しました"
            error_placeholder.error(f"❌ {url[:50]}...: {error_msg}")
            progress_placeholder.empty()
            return {'url': url, 'success': False, 'error': error_msg}
            
    except subprocess.CalledProcessError as e:
        error_msg = f"ダウンロードエラー: {e}"
        error_placeholder.error(f"❌ {url[:50]}...: {error_msg}")
        progress_placeholder.empty()
        return {'url': url, 'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = f"予期しないエラー: {str(e)}"
        error_placeholder.error(f"❌ {url[:50]}...: {error_msg}")
        progress_placeholder.empty()
        return {'url': url, 'success': False, 'error': error_msg}


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

st.set_page_config(page_title="YouTube Tools", layout="wide", page_icon="🎬")
st.markdown(CSS, unsafe_allow_html=True)
st.title("🎬 YouTube Tools")

# タブの作成
tab1, tab2 = st.tabs(["🔤 Script Translator", "📹 Video Downloader"])

# Session init
for k, v in {
    "eng_text": "",
    "jp_text": "",
    "jp_ta": "",
    "video_id": "",
    "input_method": "YouTube URL",
    "downloaded_file_path": None,
    "downloaded_file_data": None,
    "downloaded_file_name": None,
    "download_clicked": False,
    "bulk_downloaded_files": [],
    "bulk_download_progress": {},
    "bulk_download_errors": {},
}.items():
    st.session_state.setdefault(k, v)


# Tab 1: Script Translator
with tab1:
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
            # テキストエリアの値を適切に管理
            if "jp_edit" not in st.session_state:
                st.session_state["jp_edit"] = st.session_state["jp_ta"]
            
            def update_jp_text():
                """テキストエリアの変更時に呼び出される"""
                st.session_state["jp_edit"] = st.session_state["jp_text_editor"]
                st.session_state["jp_ta"] = st.session_state["jp_text_editor"]
            
            edited_jp = st.text_area(
                "Japanese Translation (editable)", 
                value=st.session_state["jp_edit"], 
                height=dynamic_height, 
                key="jp_text_editor",
                on_change=update_jp_text
            )
            
            # 現在の値を取得（リアルタイム更新のため）
            current_jp = st.session_state.get("jp_text_editor", st.session_state["jp_edit"])
            
            # 文字数を表示
            jp_char_count = len(current_jp)
            st.caption(f"文字数: {jp_char_count:,}")

        # Video embed under columns
        if st.session_state["video_id"]:
            st.markdown("---")
            st.video(f"https://www.youtube.com/watch?v={st.session_state['video_id']}")


# Tab 2: Video Downloader
with tab2:
    st.markdown("---")
    
    # ダウンロードモード選択
    download_mode = st.radio(
        "ダウンロードモード",
        ["単一動画", "バルクダウンロード"],
        horizontal=True,
        key="download_mode"
    )
    
    if download_mode == "バルクダウンロード":
        st.subheader("📥 バルクダウンロード")
        st.info("💡 複数のYouTube動画を一度にダウンロードできます。URL毎に時間指定も可能です。")
        
        # 複数URL入力
        bulk_urls_input = st.text_area(
            "YouTube URLリスト（1行に1つのURL）",
            placeholder="https://www.youtube.com/watch?v=...\nhttps://youtu.be/...\nhttps://www.youtube.com/watch?v=...",
            height=150,
            key="bulk_urls_input"
        )
        
        # URL解析とプレビュー
        bulk_urls = []
        if bulk_urls_input.strip():
            urls = [url.strip() for url in bulk_urls_input.strip().split('\n') if url.strip()]
            valid_urls = []
            invalid_urls = []
            
            for url in urls:
                if validate_youtube_url_downloader(url):
                    valid_urls.append(url)
                else:
                    invalid_urls.append(url)
            
            if valid_urls:
                st.success(f"✅ 有効なURL: {len(valid_urls)}件")
                bulk_urls = valid_urls
                
                # URLリストのプレビューを折り畳み可能な形で表示
                with st.expander(f"📋 ダウンロード予定リスト ({len(valid_urls)}件)", expanded=False):
                    for i, url in enumerate(valid_urls, 1):
                        st.text(f"{i}. {url}")
            
            if invalid_urls:
                st.error(f"❌ 無効なURL: {len(invalid_urls)}件")
                with st.expander("無効なURLを確認", expanded=False):
                    for url in invalid_urls:
                        st.text(f"• {url}")
        
        # 時間指定オプション
        st.subheader("⏰ 時間指定オプション")
        bulk_time_mode = st.radio(
            "時間指定方法",
            ["全動画とも全体をダウンロード", "全動画に同じ時間指定を適用", "URL毎に個別指定"],
            key="bulk_time_mode"
        )
        
        bulk_time_settings = {}
        
        if bulk_time_mode == "全動画に同じ時間指定を適用":
            col1_bulk, col2_bulk = st.columns(2)
            with col1_bulk:
                global_start_time = st.text_input("開始時間（全動画共通）", placeholder="例: 00:30", key="global_start_time")
            with col2_bulk:
                global_end_time = st.text_input("終了時間（全動画共通）", placeholder="例: 02:00", key="global_end_time")
            
            # 時間フォーマット検証
            global_time_valid = True
            if global_start_time and not validate_time_format(global_start_time):
                st.error("開始時間の形式が正しくありません")
                global_time_valid = False
            if global_end_time and not validate_time_format(global_end_time):
                st.error("終了時間の形式が正しくありません")
                global_time_valid = False
            
            if global_time_valid and global_start_time and global_end_time:
                for url in bulk_urls:
                    bulk_time_settings[url] = {
                        'start': normalize_time_format(global_start_time),
                        'end': normalize_time_format(global_end_time)
                    }
                st.info(f"💡 全{len(bulk_urls)}動画に {normalize_time_format(global_start_time) if global_start_time else ''} ～ {normalize_time_format(global_end_time) if global_end_time else ''} を適用")
        
        elif bulk_time_mode == "URL毎に個別指定" and bulk_urls:
            st.info("各URLに対して個別に時間を指定してください（空欄の場合は全体をダウンロード）")
            for i, url in enumerate(bulk_urls):
                with st.expander(f"🎬 動画 {i+1}: {url[:50]}..." if len(url) > 50 else f"🎬 動画 {i+1}: {url}"):
                    col1_indiv, col2_indiv = st.columns(2)
                    with col1_indiv:
                        start_time = st.text_input(f"開始時間", key=f"start_time_{i}", placeholder="例: 00:30")
                    with col2_indiv:
                        end_time = st.text_input(f"終了時間", key=f"end_time_{i}", placeholder="例: 02:00")
                    
                    # 時間指定の検証と保存
                    if start_time or end_time:
                        time_valid = True
                        if start_time and not validate_time_format(start_time):
                            st.error("開始時間の形式が正しくありません")
                            time_valid = False
                        if end_time and not validate_time_format(end_time):
                            st.error("終了時間の形式が正しくありません")
                            time_valid = False
                        
                        if time_valid and start_time and end_time:
                            bulk_time_settings[url] = {
                                'start': normalize_time_format(start_time),
                                'end': normalize_time_format(end_time)
                            }
                            st.success(f"✅ {normalize_time_format(start_time)} ～ {normalize_time_format(end_time)}")
                        elif start_time or end_time:
                            st.warning("開始時間と終了時間の両方を入力してください")
        
        # バルクダウンロード実行ボタン
        if bulk_urls:
            st.markdown("---")
            if st.button("🚀 バルクダウンロード開始", type="primary", key="bulk_download_button"):
                # 既存のバルクファイルをクリーンアップ
                cleanup_bulk_files()
                
                # プログレス表示エリアを準備
                progress_container = st.container()
                overall_progress = progress_container.progress(0)
                status_text = progress_container.empty()
                
                # 各動画のステータス表示用プレースホルダー
                video_status_placeholders = []
                for i in range(len(bulk_urls)):
                    video_status_placeholders.append({
                        'progress': progress_container.empty(),
                        'error': progress_container.empty(),
                        'success': progress_container.empty()
                    })
                
                successful_downloads = []
                total_videos = len(bulk_urls)
                
                # 各動画を順次ダウンロード
                for i, url in enumerate(bulk_urls):
                    status_text.text(f"📹 進行状況: {i+1}/{total_videos} - {url[:50]}...")
                    
                    # この動画の時間設定を取得
                    time_settings = bulk_time_settings.get(url, None)
                    
                    # ダウンロード実行
                    result = download_single_video_bulk(
                        url, 
                        time_settings, 
                        video_status_placeholders[i]['progress'],
                        video_status_placeholders[i]['error'],
                        video_status_placeholders[i]['success']
                    )
                    
                    if result['success']:
                        successful_downloads.append(result)
                        st.session_state.bulk_downloaded_files.append(result)
                    
                    # 全体プログレスを更新
                    overall_progress.progress((i + 1) / total_videos)
                
                # 完了メッセージ
                if successful_downloads:
                    status_text.success(f"🎉 バルクダウンロード完了! 成功: {len(successful_downloads)}/{total_videos}")
                    
                    # ダウンロードリンクの表示
                    st.markdown("---")
                    st.subheader("📦 ダウンロード済みファイル")
                    
                    # 全てのファイルをZIP化してダウンロード
                    if len(successful_downloads) > 1:
                        import zipfile
                        import io
                        
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                            for file_info in successful_downloads:
                                zip_file.writestr(file_info['filename'], file_info['data'])
                        
                        zip_buffer.seek(0)
                        st.download_button(
                            label="📦 全てのファイルをZIPでダウンロード",
                            data=zip_buffer.getvalue(),
                            file_name="youtube_videos_bulk.zip",
                            mime="application/zip",
                            type="primary",
                            on_click=cleanup_bulk_files,
                            key="download_all_zip"
                        )
                        st.markdown("---")
                    
                    # 個別ファイルダウンロード
                    for i, file_info in enumerate(successful_downloads):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.text(f"📹 {file_info['filename']}")
                        with col2:
                            st.download_button(
                                label="💾",
                                data=file_info['data'],
                                file_name=file_info['filename'],
                                mime="video/mp4",
                                key=f"download_individual_{i}"
                            )
                else:
                    status_text.error("❌ すべてのダウンロードに失敗しました。エラーメッセージを確認してください。")
        
        st.markdown("---")
        st.markdown("### または単一動画をダウンロード")
    
    # 単一動画ダウンロード（既存の機能）
    if download_mode == "単一動画":
        st.subheader("📹 単一動画ダウンロード")
    
    # YouTubeのURL入力
    st.subheader("YouTubeのURL")
    youtube_url_dl = st.text_input("YouTubeのURLを入力してください", placeholder="https://www.youtube.com/watch?v=...", key="youtube_url_dl")
    
    # URL検証
    url_valid_dl = True
    if youtube_url_dl:
        if not validate_youtube_url_downloader(youtube_url_dl):
            st.error("無効なYouTubeのURLです。正しいURLを入力してください。")
            url_valid_dl = False
        else:
            st.success("有効なYouTubeのURLです。")
    
    # 時間入力
    st.subheader("ダウンロード区間")
    col1_dl, col2_dl = st.columns(2)
    
    with col1_dl:
        start_time_dl = st.text_input("開始時間", placeholder="例: 00:00, 01:30, 01:22:33, 0130, 012233（空欄で動画全体）", key="start_time_dl")
        start_time_valid_dl = True
        if start_time_dl:
            if not validate_time_format(start_time_dl):
                st.error("無効な時間フォーマットです。00:00、01:22:33、0130、012233の形式で入力してください。")
                start_time_valid_dl = False
            else:
                normalized_start_dl = normalize_time_format(start_time_dl)
                st.success(f"有効な時間フォーマットです。({normalized_start_dl})")
    
    with col2_dl:
        end_time_dl = st.text_input("終了時間", placeholder="例: 00:10, 02:30, 01:25:45, 0230, 012545（空欄で動画全体）", key="end_time_dl")
        end_time_valid_dl = True
        if end_time_dl:
            if not validate_time_format(end_time_dl):
                st.error("無効な時間フォーマットです。00:00、01:22:33、0130、012233の形式で入力してください。")
                end_time_valid_dl = False
            else:
                normalized_end_dl = normalize_time_format(end_time_dl)
                st.success(f"有効な時間フォーマットです。({normalized_end_dl})")
    
    # 時間指定の状態を表示
    if not start_time_dl.strip() and not end_time_dl.strip():
        st.info("💡 時間指定なし：動画全体をダウンロードします")
    elif start_time_dl.strip() and end_time_dl.strip():
        if start_time_valid_dl and end_time_valid_dl:
            st.info(f"💡 指定区間：{normalize_time_format(start_time_dl) if start_time_dl else ''} ～ {normalize_time_format(end_time_dl) if end_time_dl else ''}")
    else:
        if start_time_dl.strip() or end_time_dl.strip():
            st.warning("⚠️ 開始時間と終了時間の両方を入力するか、両方とも空欄にしてください")
    
    # すべての入力が有効かチェック
    time_input_valid_dl = True
    if (start_time_dl.strip() and not end_time_dl.strip()) or (not start_time_dl.strip() and end_time_dl.strip()):
        time_input_valid_dl = False
    
    all_valid_dl = url_valid_dl and start_time_valid_dl and end_time_valid_dl and time_input_valid_dl and youtube_url_dl
    
    if all_valid_dl:
        # yt-dlpコマンドを構築
        cmd_dl = [
            "yt-dlp"
        ]
        
        # クラウド環境（Streamlit Cloud、Railway等）の検出
        is_cloud_environment_dl = False
        try:
            is_cloud_environment_dl = (
                "STREAMLIT_SHARING" in os.environ or 
                "streamlit" in os.environ.get("HOME", "").lower() or
                "appuser" in os.environ.get("HOME", "").lower() or
                os.path.exists("/home/appuser") or
                "RAILWAY_ENVIRONMENT" in os.environ or
                "PORT" in os.environ
            )
        except Exception:
            pass
        
        # ローカル環境でのみクッキーオプションを追加
        if not is_cloud_environment_dl:
            try:
                cmd_dl.extend(["--cookies-from-browser", "chrome"])
            except Exception:
                pass
        
        # 時間指定がある場合のみセクションダウンロードを追加
        if start_time_dl.strip() and end_time_dl.strip():
            # 時間を正規化してからダウンロードセクションの文字列を作成
            normalized_start_dl = normalize_time_format(start_time_dl)
            normalized_end_dl = normalize_time_format(end_time_dl)
            download_sections_dl = f"*{normalized_start_dl}-{normalized_end_dl}"
            cmd_dl.extend([
                "--download-sections", download_sections_dl,
                "--force-keyframes-at-cuts"
            ])
        
        cmd_dl.extend([
            "-f", "best[height<=1080]/best",
            "--merge-output-format", "mp4",
            "-o", "%(title)s_%(height)s_%(fps)s_%(vcodec.:4)s_(%(id)s).%(ext)s",
            youtube_url_dl
        ])
        
        # コマンド表示
        st.subheader("実行するコマンド")
        download_sections_for_display_dl = ""
        if start_time_dl.strip() and end_time_dl.strip():
            normalized_start_dl = normalize_time_format(start_time_dl)
            normalized_end_dl = normalize_time_format(end_time_dl)
            download_sections_for_display_dl = f"*{normalized_start_dl}-{normalized_end_dl}"
        formatted_cmd_dl = format_command_display(cmd_dl, download_sections_for_display_dl, youtube_url_dl)
        st.code(formatted_cmd_dl, language="bash")
        
        # ダウンロードボタン
        if st.button("ダウンロード開始", type="primary", key="download_button"):
            with st.spinner("ダウンロード中..."):
                try:
                    # 一意のファイル名生成のため、yt-dlpコマンドを調整
                    temp_dir = tempfile.mkdtemp()
                    temp_cmd_dl = cmd_dl.copy()
                    
                    # 一時ディレクトリに出力するように変更
                    for i, arg in enumerate(temp_cmd_dl):
                        if arg == "-o":
                            temp_cmd_dl[i+1] = os.path.join(temp_dir, temp_cmd_dl[i+1])
                            break
                    
                    # yt-dlpコマンドを実行
                    result = subprocess.run(temp_cmd_dl, check=True, capture_output=True, text=True)
                    st.success("ダウンロードが完了しました！")
                    if result.stdout:
                        st.text_area("出力:", result.stdout, height=200)
                    
                    # 一時ディレクトリからダウンロードされたファイルを取得
                    temp_files = glob.glob(os.path.join(temp_dir, "*.mp4"))
                    
                    if temp_files:
                        # 最新のファイルを取得
                        temp_file = temp_files[0]
                        original_name = os.path.basename(temp_file)
                        
                        # 現在のディレクトリで一意のファイル名を生成
                        final_path = get_unique_filename(original_name)
                        
                        # ファイルを現在のディレクトリにコピー
                        shutil.move(temp_file, final_path)
                        
                        # ファイルをバイナリで読み込み
                        with open(final_path, "rb") as f:
                            file_data = f.read()
                        
                        # セッション状態に保存
                        st.session_state.downloaded_file_path = final_path
                        st.session_state.downloaded_file_data = file_data
                        st.session_state.downloaded_file_name = os.path.basename(final_path)
                        
                        # 一時ディレクトリをクリーンアップ
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    else:
                        # 一時ディレクトリをクリーンアップ
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        st.error("ダウンロードに失敗しました。")
                        
                except subprocess.CalledProcessError as e:
                    st.error(f"エラーが発生しました: {e}")
                    if e.stderr:
                        st.text_area("エラー詳細:", e.stderr, height=200)
                    # 一時ディレクトリをクリーンアップ
                    if 'temp_dir' in locals():
                        shutil.rmtree(temp_dir, ignore_errors=True)
                except FileNotFoundError:
                    st.error("yt-dlpが見つかりません。yt-dlpがインストールされているか確認してください。")
                    # 一時ディレクトリをクリーンアップ
                    if 'temp_dir' in locals():
                        shutil.rmtree(temp_dir, ignore_errors=True)
    
    # ダウンロードファイルがある場合、ダウンロードボタンを表示
    if st.session_state.downloaded_file_data is not None:
        st.markdown("---")
        st.subheader("📥 ファイルダウンロード")
        
        # ダウンロードボタン（クリック時に自動削除）
        download_button_file = st.download_button(
            label="💾 ファイルをダウンロード",
            data=st.session_state.downloaded_file_data,
            file_name=st.session_state.downloaded_file_name,
            mime="video/mp4",
            type="primary",
            on_click=cleanup_server_file,
            key="download_file_button"
        )


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