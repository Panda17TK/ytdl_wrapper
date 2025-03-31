import streamlit as st
import os
import yt_dlp
import re
import logging
import psutil

from datetime import timedelta
from time import sleep
from urllib.parse import urlparse, parse_qsl

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('yt_downloader.log'),
        logging.StreamHandler()
    ]
)

# 共通設定
CONFIG = {
    "OUTPUT_DIR": os.path.abspath("./downloads"),
    "FFMPEG_PATH": r"C:\Users\banti\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-7.1-essentials_build\bin\ffmpeg.exe",
    "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "COOKIES": os.path.abspath("cookies.txt"),
    "MAX_RETRIES": 5,
    "TIMEOUT": 30
}

def kill_browser_processes():
    """ブラウザプロセスを強制終了"""
    browsers = ['chrome', 'firefox', 'msedge']
    killed = False
    for proc in psutil.process_iter(['name']):
        if any(browser in proc.info['name'].lower() for browser in browsers):
            try:
                proc.kill()
                killed = True
                logging.info(f"プロセス終了: {proc.info['name']}")
            except psutil.NoSuchProcess:
                pass
    return killed

def sanitize_filename(name):
    """ファイル名の無効文字を置換"""
    return re.sub(r'[\\/*?:"<>|]', "_", name.strip())

def setup_environment():
    """環境設定チェック"""
    yt_dlp.utils._PROGRESS_STRLEN = 80
    
    # FFmpeg存在確認
    if not os.path.exists(CONFIG["FFMPEG_PATH"]):
        st.error(f"FFmpegが見つかりません: {CONFIG['FFMPEG_PATH']}")
        logging.error("FFmpegパスが存在しません")
        return False
    
    # 出力ディレクトリ作成
    os.makedirs(CONFIG["OUTPUT_DIR"], exist_ok=True)
    return True

def validate_cookies():
    """クッキーの詳細検証"""
    if not os.path.exists(CONFIG["COOKIES"]):
        st.error("クッキーファイルが存在しません")
        return False
    
    # Netscape形式チェック
    with open(CONFIG["COOKIES"], 'r') as f:
        if not f.readline().startswith("# Netscape HTTP Cookie File"):
            st.error("クッキーファイル形式が不正です")
            return False

    # 必須クッキーチェック
    required_cookies = ['LOGIN_INFO', 'SID', 'HSID', 'SSID']
    with open(CONFIG["COOKIES"], 'r') as f:
        content = f.read()
        if not any(cookie in content for cookie in required_cookies):
            st.error("有効なYouTubeクッキーが不足しています")
            return False
            
    return True

def validate_url(url, is_playlist=False):
    """
    強化版URL検証関数
    YouTubeのURL形式を正規表現で厳密にチェック
    """
    # 正規表現パターンの改良
    youtube_pattern = re.compile(
        r'^https?://(www\.)?(youtube\.com|youtu\.be)/'
        r'(watch\?v=|playlist\?list=|shorts/|live/|embed/|v/|e/|attribution_link\?a=)[\w-]+'
    )
    
    # 基本的な形式チェック
    if not youtube_pattern.match(url):
        return False
    
    # パラメータの詳細チェック
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query))
    
    if is_playlist:
        return 'list' in params and len(params['list']) == 34  # プレイリストIDの長さチェック
    else:
        # 動画IDの有効性チェック（11文字のYouTube標準ID）
        return ('v' in params and len(params['v']) == 11) or '/shorts/' in url

def refresh_cookies():
    """クッキーファイル再生成"""
    if os.path.exists(CONFIG["COOKIES"]):
        os.remove(CONFIG["COOKIES"])
    
    # ブラウザ終了確認
    if kill_browser_processes():
        st.info("ブラウザを終了しました")
    
    # クッキー生成コマンド
    cmd = f'yt-dlp --cookies-from-browser chrome --cookies "{CONFIG["COOKIES"]}"'
    exit_code = os.system(cmd)
    
    if exit_code != 0 or not os.path.exists(CONFIG["COOKIES"]):
        st.error("クッキー生成に失敗しました")
        return False
    return True

def get_video_info(url):
    """動画情報取得（拡張版）"""
    if not validate_cookies():
        return None

    ydl_opts = {
        'quiet': True,
        'ffmpeg_location': CONFIG["FFMPEG_PATH"],
        'cookies': CONFIG["COOKIES"],
        'socket_timeout': CONFIG["TIMEOUT"]
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            format_selector = list(ydl.build_format_selector('bestvideo+bestaudio')(info))
            
            if not format_selector:
                st.error("対応フォーマットなし")
                return None

            best_format = format_selector[0]
            filesize = best_format.get('filesize') or best_format.get('filesize_approx', 0)
            
            return {
                'title': sanitize_filename(info.get('title', '無題')),
                'duration': str(timedelta(seconds=info['duration'])) if info.get('duration') else '不明',
                'thumbnail': info.get('thumbnail', ''),
                'view_count': f"{info.get('view_count', 0):,}",
                'uploader': info.get('uploader', '不明'),
                'resolution': best_format.get('height', '不明'),
                'filesize': f"{filesize / 1024 / 1024:.2f} MB" if filesize else '不明',
                'format_note': best_format.get('format_note', '不明')
            }
    except Exception as e:
        st.error(f"情報取得エラー: {str(e)}")
        return None

def progress_hook(d):
    """進捗表示の強化"""
    if d.get('status') == 'downloading':
        progress_data = {
            'percent': d.get('_percent_str', 'N/A'),
            'speed': d.get('_speed_str', 'N/A'),
            'eta': d.get('_eta_str', 'N/A')
        }
        st.session_state.progress = progress_data
    elif d.get('status') == 'finished':
        st.session_state.progress = {'status': 'complete'}

def download_video(url, output_dir):
    """強化版ダウンロード処理"""
    if not validate_cookies():
        return False

    ydl_opts = {
        'format': 'bestvideo[height>=1080]+bestaudio/best',
        'cookies': CONFIG["COOKIES"],
        'user_agent': CONFIG["USER_AGENT"],
        'ffmpeg_location': CONFIG["FFMPEG_PATH"],
        'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'retries': CONFIG["MAX_RETRIES"],
        'ignoreerrors': False,
        'progress_hooks': [progress_hook],
        'force_ipv4': True,
        'referer': 'https://www.youtube.com/'
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.download([url])
            return result == 0
    except yt_dlp.utils.DownloadError as e:
        handle_download_error(e)
        return False

def handle_download_error(e):
    """エラーハンドリング"""
    error_msg = str(e)
    if "Sign in to confirm your age" in error_msg:
        st.error("年齢確認が必要です。クッキーを更新してください。")
    elif "HTTP Error 403" in error_msg:
        st.error("アクセスが拒否されました。VPNを試すか時間をおいて再試行してください。")
    else:
        st.error(f"不明なエラー: {error_msg}")

def playlist_mode(output_dir):
    """プレイリスト処理"""
    with st.form("playlist_form"):
        url = st.text_input("プレイリストURL")
        if st.form_submit_button("開始"):
            if validate_url(url, True):
                process_playlist(url, output_dir)

def process_playlist(url, output_dir):
    """プレイリスト処理コア"""
    ydl_opts = {
        'extract_flat': True,
        'ignoreerrors': True,
        'quiet': True,
        'ffmpeg_location': CONFIG["FFMPEG_PATH"],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            playlist = ydl.extract_info(url, download=False)
        
        playlist_name = sanitize_filename(playlist.get('title', '無題プレイリスト'))
        playlist_dir = os.path.join(output_dir, playlist_name)
        os.makedirs(playlist_dir, exist_ok=True)
        
        total = len(playlist['entries'])
        progress_bar = st.progress(0)
        success_count = 0
        
        for idx, entry in enumerate(playlist['entries']):
            video_url = f"https://youtu.be/{entry.get('id', '')}"
            title = entry.get('title', f"動画{idx+1}")
            
            with st.expander(f"{idx+1}. {sanitize_filename(title)}"):
                if download_video(video_url, playlist_dir):
                    success_count += 1
                progress_bar.progress((idx+1)/total)
        
        st.success(f"完了: {success_count}/{total}件")
    except Exception as e:
        st.error(f"エラー: {str(e)}")

def main_ui():
    """メインUI"""
    st.set_page_config(
        page_title="YouTubeダウンローダー Pro",
        page_icon="🎬",
        layout="wide"
    )
    
    st.title("🎬 YouTubeダウンローダー Pro")
    
    with st.sidebar:
        st.header("設定")
        CONFIG["OUTPUT_DIR"] = st.text_input("保存先", value=CONFIG["OUTPUT_DIR"])
        os.makedirs(CONFIG["OUTPUT_DIR"], exist_ok=True)
        
        if st.button("クッキー再生成"):
            if refresh_cookies():
                st.success("クッキーを更新しました")
            else:
                st.error("更新に失敗しました")

    tab1, tab2 = st.tabs(["単体ダウンロード", "プレイリスト"])
    
    with tab1:
        url = st.text_input("動画URL")
        if url and validate_url(url, False):
            if info := get_video_info(url):
                col1, col2 = st.columns([1, 3])
                with col1:
                    st.image(info['thumbnail'], use_column_width=True)
                with col2:
                    st.markdown(f"""
                    ### {info['title']}
                    - **アップローダー**: {info['uploader']}
                    - **再生時間**: {info['duration']}
                    - **解像度**: {info['resolution']}p
                    """)
                    
                    if st.button("ダウンロード開始"):
                        download_dir = os.path.join(CONFIG["OUTPUT_DIR"], sanitize_filename(info['uploader']))
                        os.makedirs(download_dir, exist_ok=True)
                        if download_video(url, download_dir):
                            st.success("ダウンロード完了")

    with tab2:
        playlist_mode(CONFIG["OUTPUT_DIR"])

if __name__ == "__main__":
    if setup_environment():
        main_ui()
