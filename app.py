import os
import subprocess
import tempfile
import shutil
import streamlit as st

st.set_page_config(page_title="Simple YouTube Downloader", layout="centered", page_icon="📹")
st.title("📹 Simple YouTube Downloader")

# セッション状態の初期化
if 'downloaded_file' not in st.session_state:
    st.session_state.downloaded_file = None

# URL入力
url = st.text_input("YouTube URLを入力してください:", placeholder="https://www.youtube.com/watch?v=...")

# ダウンロードボタン
if st.button("ダウンロード", type="primary", disabled=not url):
    if url:
        with st.spinner("ダウンロード中..."):
            try:
                # 一時ディレクトリを作成
                temp_dir = tempfile.mkdtemp()
                
                # yt-dlpコマンドを実行
                cmd = [
                    "yt-dlp",
                    "-o", os.path.join(temp_dir, "%(title)s.%(ext)s"),
                    url
                ]
                
                result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                
                # ダウンロードされたファイルを探す
                files = os.listdir(temp_dir)
                if files:
                    file_path = os.path.join(temp_dir, files[0])
                    
                    # ファイルを読み込み
                    with open(file_path, "rb") as f:
                        file_data = f.read()
                    
                    # セッション状態に保存
                    st.session_state.downloaded_file = {
                        'data': file_data,
                        'name': files[0]
                    }
                    
                    st.success("ダウンロードが完了しました！")
                else:
                    st.error("ファイルが見つかりませんでした。")
                
                # 一時ディレクトリを削除
                shutil.rmtree(temp_dir, ignore_errors=True)
                
            except subprocess.CalledProcessError as e:
                st.error(f"ダウンロードエラー: {e}")
                if e.stderr:
                    st.text_area("詳細:", e.stderr, height=100)
            except FileNotFoundError:
                st.error("yt-dlpがインストールされていません。")

# ダウンロードファイルがある場合、ダウンロードボタンを表示
if st.session_state.downloaded_file:
    st.download_button(
        label="💾 ファイルをダウンロード",
        data=st.session_state.downloaded_file['data'],
        file_name=st.session_state.downloaded_file['name'],
        type="primary"
    )