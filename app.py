import os
import subprocess
import tempfile
import shutil
import streamlit as st
import re

st.set_page_config(page_title="YouTube HD Downloader", layout="centered", page_icon="📹")
st.title("📹 YouTube HD Downloader")
st.markdown("高画質（最大1080p）でYouTube動画をダウンロード")

# URL入力
url = st.text_input("YouTube URLを入力してください:", placeholder="https://www.youtube.com/watch?v=...")

# 画質選択
col1, col2 = st.columns(2)
with col1:
    quality = st.selectbox(
        "画質を選択:",
        ["1080p (フルHD)", "720p (HD)", "480p", "360p", "最高画質（自動）"],
        index=0
    )

with col2:
    format_type = st.radio(
        "フォーマット:",
        ["MP4 (動画)", "音声のみ (MP3)"]
    )

# 画質マッピング
quality_map = {
    "1080p (フルHD)": "1080",
    "720p (HD)": "720",
    "480p": "480",
    "360p": "360",
    "最高画質（自動）": "best"
}

# ダウンロードボタン
if st.button("🚀 ダウンロード開始", type="primary", disabled=not url):
    if url:
        with st.spinner("ダウンロード中... (高画質の場合は時間がかかることがあります)"):
            try:
                # 一時ディレクトリを作成
                temp_dir = tempfile.mkdtemp()
                
                # 動画情報を取得
                info_cmd = ["yt-dlp", "--print", "title", url]
                title_result = subprocess.run(info_cmd, capture_output=True, text=True, check=True)
                video_title = title_result.stdout.strip()
                
                # プログレスバー用のプレースホルダー
                progress_text = st.empty()
                progress_bar = st.progress(0)
                
                if format_type == "MP4 (動画)":
                    selected_quality = quality_map[quality]
                    
                    if selected_quality == "best":
                        # 最高画質を自動選択
                        format_string = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
                    else:
                        # 指定された画質でダウンロード（映像＋音声）
                        # 1080pの場合、映像と音声を別々にダウンロードして結合
                        format_string = f"bestvideo[height<={selected_quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={selected_quality}][ext=mp4]/best"
                    
                    # yt-dlpコマンド（高画質版）
                    cmd = [
                        "yt-dlp",
                        "-f", format_string,
                        "--merge-output-format", "mp4",  # 出力フォーマットをMP4に統一
                        "-o", os.path.join(temp_dir, "%(title)s.%(ext)s"),
                        "--no-playlist",  # プレイリストの場合でも単一動画のみ
                        "--progress",  # 進捗表示
                        url
                    ]
                else:
                    # 音声のみ（MP3）
                    cmd = [
                        "yt-dlp",
                        "-x",  # 音声のみ抽出
                        "--audio-format", "mp3",
                        "--audio-quality", "0",  # 最高音質
                        "-o", os.path.join(temp_dir, "%(title)s.%(ext)s"),
                        "--no-playlist",
                        url
                    ]
                
                # コマンド実行
                progress_text.text(f"📥 ダウンロード中: {video_title[:50]}...")
                
                # プロセスを実行してリアルタイムで出力を取得
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                # 進捗を解析して表示
                for line in process.stdout:
                    # 進捗パーセンテージを探す
                    match = re.search(r'\[download\]\s+(\d+\.?\d*)%', line)
                    if match:
                        percent = float(match.group(1))
                        progress_bar.progress(int(percent))
                        
                        # 速度とETA情報も取得
                        speed_match = re.search(r'at\s+(\S+)', line)
                        eta_match = re.search(r'ETA\s+(\S+)', line)
                        
                        status_text = f"📥 ダウンロード中: {percent:.1f}%"
                        if speed_match:
                            status_text += f" | 速度: {speed_match.group(1)}"
                        if eta_match:
                            status_text += f" | 残り時間: {eta_match.group(1)}"
                        progress_text.text(status_text)
                
                process.wait()
                
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(process.returncode, cmd)
                
                # ダウンロードされたファイルを探す
                files = os.listdir(temp_dir)
                if files:
                    file_path = os.path.join(temp_dir, files[0])
                    file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB単位
                    
                    # ファイルを読み込み
                    with open(file_path, "rb") as f:
                        file_data = f.read()
                    
                    # 成功メッセージ
                    progress_bar.progress(100)
                    progress_text.empty()
                    st.success(f"✅ ダウンロード完了！")
                    
                    # ファイル情報表示
                    col1, col2 = st.columns(2)
                    with col1:
                        st.info(f"📁 ファイル名: {files[0][:50]}...")
                    with col2:
                        st.info(f"📊 サイズ: {file_size:.1f} MB")
                    
                    # ダウンロードボタン
                    st.download_button(
                        label="💾 ファイルを保存",
                        data=file_data,
                        file_name=files[0],
                        mime="video/mp4" if format_type == "MP4 (動画)" else "audio/mpeg",
                        type="primary"
                    )
                else:
                    st.error("ファイルが見つかりませんでした。")
                
                # 一時ディレクトリを削除
                shutil.rmtree(temp_dir, ignore_errors=True)
                
            except subprocess.CalledProcessError as e:
                st.error(f"ダウンロードエラー: URLが正しいか確認してください。")
                with st.expander("エラーの詳細"):
                    if e.stderr:
                        st.code(e.stderr)
                    st.markdown("""
                    **考えられる原因:**
                    - 無効なURL
                    - 動画が削除されている
                    - 地域制限がある
                    - ffmpegがインストールされていない（高画質ダウンロードに必要）
                    """)
            except FileNotFoundError:
                st.error("yt-dlpがインストールされていません。")
                with st.expander("インストール方法"):
                    st.markdown("""
                    ### 必要なツールのインストール:
                    
                    **1. yt-dlpのインストール:**
                    ```bash
                    pip install yt-dlp
                    ```
                    
                    **2. ffmpegのインストール（高画質ダウンロードに必須）:**
                    
                    - **Windows:** [ffmpeg公式サイト](https://ffmpeg.org/download.html)からダウンロード
                    - **Mac:** `brew install ffmpeg`
                    - **Linux:** `sudo apt-get install ffmpeg`
                    
                    ffmpegは1080pなどの高画質動画をダウンロードする際に、
                    映像と音声を結合するために必要です。
                    """)
            except Exception as e:
                st.error(f"予期しないエラー: {str(e)}")

# 使い方の説明
with st.expander("📖 使い方・注意事項"):
    st.markdown("""
    ### 使い方:
    1. YouTube動画のURLをコピー
    2. URL欄に貼り付け
    3. 希望の画質を選択
    4. ダウンロードボタンをクリック
    
    ### 高画質ダウンロードについて:
    - **1080p動画**: 映像と音声が別々にダウンロードされ、自動的に結合されます
    - **ffmpegが必要**: 高画質動画の処理にはffmpegのインストールが必須です
    - **ファイルサイズ**: 1080pは720pの約2倍のサイズになります
    - **ダウンロード時間**: 高画質ほど時間がかかります
    
    ### トラブルシューティング:
    - **1080pがダウンロードできない場合**:
        - ffmpegがインストールされているか確認
        - 元動画が1080pで提供されているか確認
    - **エラーが出る場合**:
        - URLが正しいか確認
        - プライベート動画や年齢制限のある動画は不可
    
    ### 注意:
    - 著作権で保護されたコンテンツのダウンロードは避けてください
    - 個人利用の範囲でご使用ください
    """)

# フッター
st.markdown("---")
st.markdown("⚠️ 動画の著作権を尊重してご利用ください")