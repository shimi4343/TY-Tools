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
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
import tempfile
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import ssl
import socket

import streamlit as st
import yt_dlp
import anthropic
import requests
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
# yt-dlp configuration
# ---------------------------------------------------------------------------

def get_ydl_opts() -> Dict[str, Any]:
    """yt-dlpのオプションを返す（Streamlit Community Cloud用に最適化）"""
    # Streamlit Cloud用の一時ディレクトリ
    temp_dir = tempfile.gettempdir()
    
    # Cloud環境での字幕取得を最適化
    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en', 'en-US', 'en-GB', 'en-CA', 'en-AU', 'en-IN'],
        'subtitlesformat': 'best',
        'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
        'cachedir': temp_dir,
        
        # Streamlit Cloud対策を強化
        'socket_timeout': 60,
        'retries': 8,
        'fragment_retries': 8,
        'extractor_retries': 3,
        'retry_sleep': 2,
        
        # Cloud環境向けヘッダー設定
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        },
        
        # ネットワーク設定
        'prefer_insecure': False,
        'call_home': False,
        'no_color': True,
        'no_check_certificate': False,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        
        # エラー処理
        'ignoreerrors': False,
        'abort_on_unavailable_fragment': False,
        'keep_fragments': False,
        
        # パフォーマンス最適化
        'concurrent_fragment_downloads': 1,
        'buffer_size': 1024,
        'http_chunk_size': 10485760,
    }
    
    return base_opts


def get_fallback_ydl_opts() -> Dict[str, Any]:
    """フォールバック用のyt-dlpオプション（より保守的な設定）"""
    temp_dir = tempfile.gettempdir()
    
    return {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en'],
        'subtitlesformat': 'vtt',
        'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
        'cachedir': temp_dir,
        'socket_timeout': 30,
        'retries': 3,
        'http_headers': {
            'User-Agent': 'yt-dlp/2023.12.30',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
        },
        'no_color': True,
        'geo_bypass': True,
    }


def get_minimal_ydl_opts() -> Dict[str, Any]:
    """最小限のyt-dlpオプション（最後の手段）"""
    temp_dir = tempfile.gettempdir()
    
    return {
        'quiet': True,
        'skip_download': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en'],
        'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
        'socket_timeout': 20,
        'retries': 1,
        'no_color': True,
    }

# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def extract_video_id(url: str) -> str:
    """YouTube URLから動画IDを抽出"""
    for pattern in (r"(?<=v=)[A-Za-z0-9_-]{11}", r"youtu\.be/([A-Za-z0-9_-]{11})", r"embed/([A-Za-z0-9_-]{11})"):
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


def parse_non_json_subtitle(subtitle_content: str) -> str:
    """VTT/TTML等の非JSON形式の字幕をテキストに変換"""
    text_parts = []
    
    # VTT形式の場合
    if 'WEBVTT' in subtitle_content:
        lines = subtitle_content.split('\n')
        for line in lines:
            line = line.strip()
            # タイムスタンプ行をスキップ
            if '-->' in line or line.startswith('WEBVTT') or line.startswith('NOTE') or not line:
                continue
            # HTMLタグを削除
            line = re.sub(r'<[^>]+>', '', line)
            if line:
                text_parts.append(line)
    
    # TTML形式の場合
    elif '<tt' in subtitle_content and 'xml' in subtitle_content:
        # 簡易的なXML解析
        try:
            root = ET.fromstring(subtitle_content)
            for elem in root.iter():
                if elem.text:
                    text = elem.text.strip()
                    if text:
                        text_parts.append(text)
        except ET.ParseError:
            # XMLパースに失敗した場合は正規表現でテキストを抽出
            text_parts = re.findall(r'>(.*?)</', subtitle_content)
            text_parts = [t.strip() for t in text_parts if t.strip()]
    
    # SRV形式の場合（簡易的な処理）
    else:
        # 基本的なテキスト抽出
        lines = subtitle_content.split('\n')
        for line in lines:
            line = line.strip()
            # タイムスタンプや空行をスキップ
            if not line or '-->' in line or line.isdigit():
                continue
            # HTMLタグを削除
            line = re.sub(r'<[^>]+>', '', line)
            if line:
                text_parts.append(line)
    
    return ' '.join(text_parts)


def fetch_transcript_with_requests(video_id: str) -> tuple[str, str]:
    """
    requestsを使用してYouTubeの内部APIから字幕を取得する高度なアプローチ
    Chrome拡張機能が使用するのと同様の手法
    """
    try:
        # YouTube視聴ページにアクセスして必要な情報を取得
        session = requests.Session()
        
        # 完全なブラウザ環境を模倣
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
        
        # YouTubeページを取得
        url = f"https://www.youtube.com/watch?v={video_id}"
        response = session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        html_content = response.text
        
        # 字幕情報を抽出（正規表現を使用）
        import re
        
        # captionTracksを検索
        caption_pattern = r'"captionTracks":\s*(\[.*?\])'
        caption_match = re.search(caption_pattern, html_content)
        
        if not caption_match:
            # 別のパターンを試行
            caption_pattern = r'"captions":\s*{[^}]*"playerCaptionsTracklistRenderer":\s*{[^}]*"captionTracks":\s*(\[.*?\])'
            caption_match = re.search(caption_pattern, html_content)
        
        if not caption_match:
            return "", "ページから字幕情報を抽出できませんでした。"
        
        # JSON形式の字幕情報をパース
        captions_json = caption_match.group(1)
        
        # 文字列を適切にエスケープしてJSONとして解析
        captions_json = captions_json.replace('\\', '\\\\').replace('\\"', '"')
        
        try:
            import json
            captions_data = json.loads(captions_json)
        except json.JSONDecodeError:
            # 手動でパースを試行
            captions_data = []
            url_pattern = r'"baseUrl":"([^"]+)"'
            lang_pattern = r'"languageCode":"([^"]+)"'
            
            urls = re.findall(url_pattern, captions_json)
            langs = re.findall(lang_pattern, captions_json)
            
            for url, lang in zip(urls, langs):
                if lang.startswith('en'):
                    captions_data.append({
                        'baseUrl': url.replace('\\u0026', '&'),
                        'languageCode': lang
                    })
        
        # 英語字幕を検索
        english_caption_url = None
        for caption in captions_data:
            if isinstance(caption, dict):
                lang_code = caption.get('languageCode', '')
                if lang_code.startswith('en'):
                    english_caption_url = caption.get('baseUrl', '')
                    break
        
        if not english_caption_url:
            return "", "英語字幕URLが見つかりませんでした。"
        
        # 字幕XMLを取得
        caption_response = session.get(english_caption_url, headers=headers, timeout=30)
        caption_response.raise_for_status()
        
        # XML形式の字幕をパース
        caption_xml = caption_response.text
        
        # XML から テキストを抽出
        text_pattern = r'<text[^>]*>(.*?)</text>'
        text_matches = re.findall(text_pattern, caption_xml, re.DOTALL)
        
        if not text_matches:
            return "", "字幕テキストを抽出できませんでした。"
        
        # HTMLエンティティをデコード
        import html
        transcript_parts = []
        for match in text_matches:
            # HTMLタグを除去
            clean_text = re.sub(r'<[^>]+>', '', match)
            # HTMLエンティティをデコード
            clean_text = html.unescape(clean_text)
            if clean_text.strip():
                transcript_parts.append(clean_text.strip())
        
        transcript_text = ' '.join(transcript_parts)
        
        if not transcript_text:
            return "", "字幕テキストが空でした。"
        
        return transcript_text, ""
        
    except requests.exceptions.RequestException as e:
        return "", f"リクエストエラー: {str(e)}"
    except Exception as e:
        return "", f"予期しないエラー: {type(e).__name__}: {str(e)}"


def fetch_transcript_youtube_api(video_id: str) -> tuple[str, str]:
    """
    YouTubeの内部APIを直接呼び出す手法
    """
    try:
        session = requests.Session()
        
        # 最新のヘッダーを設定
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://www.youtube.com',
            'Referer': f'https://www.youtube.com/watch?v={video_id}',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        }
        
        # YouTube内部APIエンドポイント
        api_url = f"https://www.youtube.com/youtubei/v1/player"
        
        # APIリクエストのペイロード
        payload = {
            'context': {
                'client': {
                    'clientName': 'WEB',
                    'clientVersion': '2.20231219.04.00',
                }
            },
            'videoId': video_id,
            'params': 'CgIQAQ%3D%3D'  # 字幕パラメータ
        }
        
        response = session.post(api_url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        player_data = response.json()
        
        # 字幕情報を抽出
        captions = player_data.get('captions', {})
        caption_tracks = captions.get('playerCaptionsTracklistRenderer', {}).get('captionTracks', [])
        
        # 英語字幕を検索
        english_caption_url = None
        for track in caption_tracks:
            if track.get('languageCode', '').startswith('en'):
                english_caption_url = track.get('baseUrl', '')
                break
        
        if not english_caption_url:
            return "", "API経由で英語字幕が見つかりませんでした。"
        
        # 字幕XMLを取得
        caption_response = session.get(english_caption_url, headers=headers, timeout=30)
        caption_response.raise_for_status()
        
        # XMLをパース
        caption_xml = caption_response.text
        text_pattern = r'<text[^>]*>(.*?)</text>'
        text_matches = re.findall(text_pattern, caption_xml, re.DOTALL)
        
        if not text_matches:
            return "", "API経由で字幕テキストを抽出できませんでした。"
        
        # テキストを結合
        import html
        transcript_parts = []
        for match in text_matches:
            clean_text = re.sub(r'<[^>]+>', '', match)
            clean_text = html.unescape(clean_text)
            if clean_text.strip():
                transcript_parts.append(clean_text.strip())
        
        transcript_text = ' '.join(transcript_parts)
        
        if not transcript_text:
            return "", "API経由で取得した字幕テキストが空でした。"
        
        return transcript_text, ""
        
    except requests.exceptions.RequestException as e:
        return "", f"API リクエストエラー: {str(e)}"
    except Exception as e:
        return "", f"API 予期しないエラー: {type(e).__name__}: {str(e)}"


@st.cache_data(show_spinner=False, ttl=3600)  # 1時間キャッシュ
def fetch_english_transcript_ytdlp(video_id: str) -> tuple[str, str]:
    """
    複数の手法を組み合わせて字幕を取得（Chrome拡張機能レベルの信頼性）
    Returns: (transcript_text, error_message)
    """
    
    # 高度なアプローチを優先的に試行
    advanced_methods = [
        ('requests_html', lambda: fetch_transcript_with_requests(video_id)),
        ('youtube_api', lambda: fetch_transcript_youtube_api(video_id)),
    ]
    
    # 高度な手法を試行
    for method_name, method_func in advanced_methods:
        try:
            transcript, error = method_func()
            if transcript:
                return transcript, ""
        except Exception as e:
            continue  # 次の手法を試行
    
    # yt-dlpのフォールバック
    methods = [
        ('primary', get_ydl_opts()),
        ('fallback1', get_fallback_ydl_opts()),
        ('fallback2', get_minimal_ydl_opts())
    ]
    
    for method_name, ydl_opts in methods:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 動画情報を取得
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                
                if not info:
                    continue
                
                # 字幕を確認
                subtitles = info.get('subtitles', {})
                automatic_captions = info.get('automatic_captions', {})
                
                # 英語字幕を探す
                subtitle_url = None
                subtitle_source = None
                
                # サポートする字幕形式（優先順位順）
                supported_formats = ['json3', 'vtt', 'ttml', 'srv1', 'srv2', 'srv3']
                
                # サポートする言語コード（優先順位順）
                supported_langs = ['en', 'en-US', 'en-GB', 'en-CA', 'en-AU', 'en-IN']
                
                # 1. 自動生成字幕を最優先で確認
                for lang in supported_langs:
                    if lang in automatic_captions:
                        for fmt in supported_formats:
                            for sub in automatic_captions[lang]:
                                if sub.get('ext') == fmt:
                                    subtitle_url = sub['url']
                                    subtitle_source = f"auto-{lang}-{fmt}-{method_name}"
                                    break
                            if subtitle_url:
                                break
                        if subtitle_url:
                            break
                
                # 2. 自動字幕がない場合のみ手動字幕を確認
                if not subtitle_url:
                    for lang in supported_langs:
                        if lang in subtitles:
                            for fmt in supported_formats:
                                for sub in subtitles[lang]:
                                    if sub.get('ext') == fmt:
                                        subtitle_url = sub['url']
                                        subtitle_source = f"manual-{lang}-{fmt}-{method_name}"
                                        break
                                if subtitle_url:
                                    break
                            if subtitle_url:
                                break
                
                if not subtitle_url:
                    continue  # 次の手法を試行
                
                # 字幕データをダウンロード
                try:
                    import ssl
                    # SSL証明書の検証を無効化（Cloud環境対応）
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    
                    request = urllib.request.Request(subtitle_url)
                    request.add_header('User-Agent', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36')
                    
                    with urllib.request.urlopen(request, context=ssl_context, timeout=30) as response:
                        subtitle_content = response.read().decode('utf-8')
                        
                    # 形式に応じて処理
                    if 'json3' in subtitle_source:
                        subtitle_json = json.loads(subtitle_content)
                        if 'events' in subtitle_json:
                            transcript_text = parse_subtitle_json(subtitle_json['events'])
                        else:
                            transcript_text = parse_subtitle_json(subtitle_json)
                    else:
                        # VTT, TTML等の場合は簡易パーサーを使用
                        transcript_text = parse_non_json_subtitle(subtitle_content)
                        
                    if transcript_text:
                        return transcript_text, ""
                        
                except (urllib.error.URLError, ssl.SSLError, socket.timeout) as e:
                    continue  # 次の手法を試行
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "Video unavailable" in error_msg:
                return "", "動画が利用できません。非公開または削除されている可能性があります。"
            elif "Sign in to confirm your age" in error_msg:
                return "", "年齢制限のある動画です。字幕を取得できません。"
            else:
                continue  # 次の手法を試行
        except Exception as e:
            continue  # 次の手法を試行
    
    # すべての手法が失敗した場合
    return "", "すべての字幕取得方法が失敗しました。「英語字幕を直接入力」オプションをお試しください。"


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


def generate_script(template: str, eng_text: str) -> str:
    """ショート動画用スクリプトを生成"""
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
    "input_method": "YouTube URL",
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
    fetch_clicked = cols_btn[0].button("🚀 Fetch / 生成")
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
    fetch_clicked = cols_btn[0].button("🚀 翻訳 / 生成")
    clear_clicked = cols_btn[1].button("✂︎ Clear")

if clear_clicked:
    for key in ("eng_text", "jp_text", "jp_ta", "script_text", "script_ta", "video_id"):
        st.session_state[key] = ""
    _rerun()

# Processing
if fetch_clicked:
    if st.session_state["input_method"] == "YouTube URL" and url:
        vid = extract_video_id(url)
        if not vid:
            st.error("動画 ID を URL から抽出できませんでした。URL を確認してください。")
            st.stop()

        with st.spinner("英語スクリプトを取得中…"):
            eng, error_msg = fetch_english_transcript_ytdlp(vid)
        
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

    with st.spinner("ショート動画台本を生成中…"):
        script = generate_script(st.session_state["prompt_template"], eng)

    st.session_state.update(
        {
            "eng_text": eng,
            "jp_text": jp,
            "jp_ta": jp,
            "script_text": script,
            "script_ta": script,
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
        len(st.session_state["jp_ta"]),
        len(st.session_state["script_ta"])
    )
    
    # 文字数に応じて高さを調整（100文字あたり約20px）
    dynamic_height = min(max(500, text_length // 100 * 20), 1000)
    
    col_eng, col_jp, col_sc = st.columns(3)

    with col_eng:
        st.text_area("English Transcript", value=st.session_state["eng_text"], height=dynamic_height, disabled=True)
    with col_jp:
        st.session_state["jp_ta"] = st.text_area("Japanese Translation (editable)", value=st.session_state["jp_ta"], height=dynamic_height)
    with col_sc:
        st.session_state["script_ta"] = st.text_area("Shorts Script (editable)", value=st.session_state["script_ta"], height=dynamic_height)

    # Video embed under columns
    if st.session_state["video_id"]:
        st.markdown("---")
        st.video(f"https://www.youtube.com/watch?v={st.session_state['video_id']}")

# Footer with debug info (開発時のみ表示)
with st.expander("🔧 Debug Info", expanded=False):
    st.caption(f"yt-dlp version: {yt_dlp.version.__version__}")
    st.caption(f"Python version: {os.sys.version}")
    st.caption(f"Streamlit version: {st.__version__}")