import os
import sys
import time
import json
import shutil
import subprocess
import glob
from datetime import datetime

# 必要ライブラリ: pip install google-generativeai groq requests google-api-python-client google-auth
import requests
import google.generativeai as genai
from groq import Groq
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import zipfile

# --- 設定 ---
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664" 
FINAL_FALLBACK_DB_ID = "2b71bc8521e38018a5c3c4b0c6b6627c"
TEMP_DIR = "temp_workspace"
CHUNK_LENGTH = 900  # 15分 (秒)

# --- 初期化処理 ---
def setup_env():
    if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)
    
    # Service Account生成
    if os.getenv("GCP_SA_KEY"):
        with open("service_account.json", "w") as f:
            f.write(os.getenv("GCP_SA_KEY"))

setup_env()

# Client Init
try:
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
except Exception as e:
    print(f"❌ Init Error: {e}")
    sys.exit(1)

# --- FFmpeg Helpers (The Core Logic) ---

def run_ffmpeg(cmd):
    """FFmpegコマンドを実行し、エラーなら例外を投げる"""
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"⚠️ FFmpeg Error: {e}")
        raise

def mix_audio_ffmpeg(file_paths):
    """複数の音声をFFmpegで1つのMP3(64k)に統合・圧縮する"""
    if not file_paths: return None
    print(f"🎛️ Mixing {len(file_paths)} tracks...", flush=True)
    
    output_path = os.path.join(TEMP_DIR, "mixed_full.mp3")
    
    # 1ファイルなら単に変換
    if len(file_paths) == 1:
        cmd = ['ffmpeg', '-y', '-i', file_paths[0], '-b:a', '64k', output_path]
    else:
        # 複数ファイルならamixフィルタで統合
        inputs = []
        for f in file_paths:
            inputs.extend(['-i', f])
        
        # amix=inputs=N:duration=longest
        filter_cmd = f"amix=inputs={len(file_paths)}:duration=longest"
        cmd = ['ffmpeg', '-y'] + inputs + ['-filter_complex', filter_cmd, '-b:a', '64k', output_path]
    
    run_ffmpeg(cmd)
    return output_path

def split_audio_ffmpeg(input_path):
    """長尺MP3を指定秒数（900秒）ごとに分割する"""
    print("🔪 Splitting audio into chunks...", flush=True)
    output_pattern = os.path.join(TEMP_DIR, "chunk_%03d.mp3")
    
    # -f segment で分割。-c copy で再エンコードなし（爆速）
    cmd = [
        'ffmpeg', '-y', '-i', input_path, 
        '-f', 'segment', '-segment_time', str(CHUNK_LENGTH), 
        '-c', 'copy', output_pattern
    ]
    run_ffmpeg(cmd)
    
    chunks = sorted(glob.glob(os.path.join(TEMP_DIR, "chunk_*.mp3")))
    print(f"➡️ Created {len(chunks)} chunks.")
    return chunks

# --- AI Helpers ---

def transcribe_with_groq(chunk_paths):
    """Groq API (Whisper Large v3) で分割ファイルを順次文字起こし"""
    full_transcript = ""
    print("🚀 Starting Groq Transcription...", flush=True)
    
    for i, chunk in enumerate(chunk_paths):
        print(f"   Processing chunk {i+1}/{len(chunk_paths)}...", flush=True)
        with open(chunk, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(chunk, os.path.basename(chunk)),
                model="whisper-large-v3",
                language="ja",
                response_format="text"
            )
            full_transcript += transcription + "\n"
            
    return full_transcript

def summarize_with_gemini(transcript_text):
    """Gemini 1.5 Flashでテキストベースの要約・構造化"""
    print("🧠 Summarizing with Gemini 1.5 Flash...", flush=True)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    あなたはプロのスマブラコーチのアシスタントAIです。
    以下はコーチングセッションの全文字起こしログです。これを分析し、指定のJSON形式で出力してください。

    【分析要件】
    1. 生徒の名前を特定せよ（不明な場合は "Unknown"）。
    2. セッションの日付を特定せよ（不明な場合は今日の日付 {datetime.now().strftime('%Y-%m-%d')}）。
    3. 内容を「現状・課題・解決策・ネクストアクション」のフレームワークで分析し、要約を作成せよ。

    【出力JSON形式】
    {{
      "student_name": "Name",
      "date": "YYYY-MM-DD",
      "summary": "要約テキスト（200文字以内）",
      "next_action": "具体的な次のアクション"
    }}

    --- TRANSCRIPT START ---
    {transcript_text[:1000000]} 
    --- TRANSCRIPT END ---
    """
    # Flashは100万トークンまでいけるので、基本的にはtruncate不要だが念のため
    
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    return json.loads(response.text)

# --- Notion Helpers ---
def notion_create_page(db_id, props, children):
    url = "https://api.notion.com/v1/pages"
    # 子供要素が多い場合は分割して追加する必要があるが、今回は簡易実装
    payload = {"parent": {"database_id": db_id}, "properties": props, "children": children[:100]} 
    res = requests.post(url, headers=HEADERS, json=payload)
    if res.status_code != 200:
        print(f"⚠️ Notion Error: {res.text}")
    return res.json()

# --- Main Flow ---

def main():
    print("--- SZ AUTO LOGGER (FFmpeg + Groq Edition) ---", flush=True)
    
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if not folder_id: return

    # 1. Check Drive
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false",
        fields="files(id, name)", orderBy="createdTime desc"
    ).execute()
    files = results.get('files', [])
    
    if not files:
        print("ℹ️ No new files.", flush=True)
        return

    for file in files:
        print(f"\n📂 Processing: {file['name']}", flush=True)
        
        # 2. Download & Extract
        file_path = os.path.join(TEMP_DIR, file['name'])
        with open(file_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, drive_service.files().get_media(fileId=file['id']))
            done = False
            while not done: _, done = downloader.next_chunk()
            
        audio_paths = []
        if file['name'].endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as z:
                z.extractall(TEMP_DIR)
                for root, _, fs in os.walk(TEMP_DIR):
                    for f in fs:
                        if f.lower().endswith(('.flac', '.mp3', '.m4a', '.wav')):
                            audio_paths.append(os.path.join(root, f))
        else:
            audio_paths.append(file_path)

        # 3. Audio Pipeline (Mix -> Split)
        mixed_file = mix_audio_ffmpeg(audio_paths)
        chunks = split_audio_ffmpeg(mixed_file)
        
        # 4. Transcribe (Groq)
        full_text = transcribe_with_groq(chunks)
        
        # 5. Summarize (Gemini)
        data = summarize_with_gemini(full_text)
        
        # 6. Notion Logic (Simplified for brevity)
        print(f"📝 Writing to Notion: {data['student_name']}")
        
        # 送信先ID決定ロジック（既存コードと同じ想定）
        # ここではInbox(Fallback)に書き込む例のみ記述
        target_db = FINAL_FALLBACK_DB_ID 
        
        props = {
            "名前": {"title": [{"text": {"content": f"{data['date']} {data['student_name']} ログ"}}]},
            "日付": {"date": {"start": data['date']}}
        }
        
        # 本文（要約 + 全文ログ）
        children = [
            {"object": "block", "type": "callout", "callout": {
                "rich_text": [{"text": {"content": data['summary']}}],
                "icon": {"emoji": "🤖"}
            }},
            {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Full Transcript"}}]}}
        ]
        
        # テキストを2000文字ごとに分割してブロック化
        for i in range(0, len(full_text), 2000):
            chunk_text = full_text[i:i+2000]
            children.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": chunk_text}}]}
            })
            
        notion_create_page(target_db, props, children)
        
        # 7. Move processed file
        # (Drive move logic here - same as before)
        print("✅ Done.")

if __name__ == "__main__":
    main()
