import os
import sys
import time
import json
import shutil
import subprocess
import glob
import re
from datetime import datetime

# --- Libraries ---
import requests
import google.generativeai as genai
from groq import Groq
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import zipfile

# --- Configuration ---
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664"
FINAL_FALLBACK_DB_ID = "2b71bc8521e38018a5c3c4b0c6b6627c"
TEMP_DIR = "temp_workspace"
CHUNK_LENGTH = 900  # 15分 (Groq API制限回避)

# ==========================================
# Phase 1: 素材の純化と準備 (Input & Normalization)
# ==========================================

def setup_env():
    """環境初期化: 一時フォルダの浄化と認証設定"""
    if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)
    
    if os.getenv("GCP_SA_KEY"):
        with open("service_account.json", "w") as f:
            f.write(os.getenv("GCP_SA_KEY"))

# 環境セットアップ実行
setup_env()

# クライアント初期化
try:
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=['https://www.googleapis.com/auth/drive'])
    drive_service = build('drive', 'v3', credentials=creds)
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    
except Exception as e:
    print(f"❌ Init Critical Error: {e}")
    sys.exit(1)


def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    return match.group(1) if match else None


def mix_audio_ffmpeg(file_paths):
    """
    [強制正規化]
    あらゆる音声ファイルを統合し、Groqが確実に処理できる
    'モノラル・64kbps・MP3' に変換する。
    """
    print(f"🎛️ Mixing & Converting {len(file_paths)} tracks...", flush=True)
    output_path = os.path.abspath(os.path.join(TEMP_DIR, "final_mix.mp3"))
    
    inputs = []
    for f in file_paths: inputs.extend(['-i', f])
    
    filter_cmd = []
    if len(file_paths) > 1:
        filter_cmd = ['-filter_complex', f'amix=inputs={len(file_paths)}:duration=longest']
        
    cmd = ['ffmpeg', '-y'] + inputs + filter_cmd + ['-ac', '1', '-b:a', '64k', output_path]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path


def split_audio_ffmpeg(input_path):
    """[分割処理] 15分ごとに分割してAPI制限を回避"""
    print("🔪 Splitting into chunks...", flush=True)
    output_pattern = os.path.join(TEMP_DIR, "chunk_%03d.mp3")
    
    cmd = [
        'ffmpeg', '-y', '-i', input_path, 
        '-f', 'segment', '-segment_time', str(CHUNK_LENGTH), 
        '-ac', '1', '-b:a', '64k', output_pattern
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return sorted(glob.glob(os.path.join(TEMP_DIR, "chunk_*.mp3")))


def transcribe_with_groq(chunk_paths):
    """[高速テキスト化] 分割MP3を順次Whisperにかける"""
    full_transcript = ""
    for chunk in chunk_paths:
        if not chunk.endswith(".mp3"): continue
        
        print(f"🚀 Groq Transcribing: {os.path.basename(chunk)}", flush=True)
        with open(chunk, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(os.path.basename(chunk), file),
                model="whisper-large-v3",
                language="ja",
                response_format="text"
            )
            full_transcript += transcription + "\n"
    return full_transcript


# ==========================================
# Phase 2: 知能分析と構造化 (The Brain)
# ==========================================

def analyze_text_with_gemini(transcript_text):
    """
    [SZメソッド分析]
    5要素(Status, Problem, Root Cause, Solution, Next Action)を厳格に抽出。
    """
    print("🧠 Gemini Analyzing (SZ Method - 5 Elements)...", flush=True)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    あなたは世界最高峰のスマブラ（Super Smash Bros.）アナリストであり、論理的かつ冷徹なコーチング記録官です。
    渡された対話ログを精読し、以下の3つのセクションを厳密なフォーマットで出力してください。

    **【Section 1: トピック別・詳細分析レポート】**
    会話の中で扱われた「主要なトピック（例：崖上がり狩り、ライン管理、復帰阻止）」をすべて抽出し、
    **トピックごとに**以下の5要素を埋めて記述すること。

    * **① 現状 (Status):** プレイヤーが現在行っている行動、癖、認識している状況。
    * **② 課題 (Problem):** その行動によって発生している具体的なデメリット。
    * **③ 原因 (Root Cause):** なぜその課題が発生しているのか（知識不足、操作ミス、判断ミス等）。
    * **④ 改善案 (Solution):** 具体的にどう行動を変えるべきか（技の変更、タイミング、意識配分）。
    * **⑤ やること (Next Action):** 次回のプレイで即座に実行すべき、具体的アクション（1行）。

    **【Section 2: 時系列ログ】**
    セッションの流れを時系列（Time-Series）で詳細に箇条書きにすること。

    **【Section 3: メタデータJSON】**
    以下のJSONのみを出力すること。
    {{
      "student_name": "生徒の名前（不明ならUnknown）",
      "date": "YYYY-MM-DD",
      "next_action": "最も優先度の高いアクション1つ"
    }}

    ---
    **[DETAILED_REPORT_START]**
    (ここにSection 1を出力)
    **[DETAILED_REPORT_END]**

    **[RAW_LOG_START]**
    (ここにSection 2を出力)
    **[RAW_LOG_END]**

    **[JSON_START]**
    (ここにSection 3を出力)
    **[JSON_END]**
    ---

    【入力テキスト】
    {transcript_text[:950000]}
    """
    
    response = model.generate_content(prompt)
    text = response.text.strip()
    
    # 正規表現で抽出
    def extract(s, e, src):
        m = re.search(f'{re.escape(s)}(.*?){re.escape(e)}', src, re.DOTALL)
        return m.group(1).strip() if m else ""

    report = extract("[DETAILED_REPORT_START]", "[DETAILED_REPORT_END]", text)
    time_log = extract("[RAW_LOG_START]", "[RAW_LOG_END]", text)
    json_str = extract("[JSON_START]", "[JSON_END]", text)
    
    try:
        data = json.loads(json_str)
    except:
        data = {"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "Check Logs"}
        
    return data, report, time_log


# ==========================================
# Phase 3: 資産化と整理 (Storage & Cleanup)
# ==========================================

def notion_query_student(student_name):
    """生徒名からTargetIDを取得"""
    db_id = sanitize_id(FINAL_CONTROL_DB_ID)
    if not db_id: return None, student_name
    
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    res = requests.post(url, headers=HEADERS, json={"filter": {"property": "Name", "title": {"contains": student_name}}})
    d = res.json()
    
    if d.get("results"):
        row = d["results"][0]
        name = row["properties"]["Name"]["title"][0]["plain_text"]
        tid = row["properties"]["TargetID"]["rich_text"]
        return (sanitize_id(tid[0]["plain_text"]), name) if tid else (None, name)
    return None, student_name


def notion_create_page_heavy(db_id, props, all_children):
    """[分割書き込み] 100ブロック制限を回避して全データを保存"""
    # 1. ページ作成
    res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json={
        "parent": {"database_id": db_id},
        "properties": props,
        "children": all_children[:100]
    })
    page_id = res.json().get('id')
    
    # 2. 追記 (Append)
    if page_id and len(all_children) > 100:
        url_append = f"https://api.notion.com/v1/blocks/{page_id}/children"
        for i in range(100, len(all_children), 100):
            chunk = all_children[i : i + 100]
            requests.patch(url_append, headers=HEADERS, json={"children": chunk})


def cleanup_drive_file(file_id, rename_to):
    """[整合性確保] リネームと移動を同時に行う"""
    # フォルダ確保
    q = f"name='processed_coaching_logs' and '{INBOX_FOLDER_ID}' in parents and trashed=false"
    folders = drive_service.files().list(q=q).execute().get('files', [])
    target_id = folders[0]['id'] if folders else drive_service.files().create(
        body={'name': 'processed_coaching_logs', 'mimeType': 'application/vnd.google-apps.folder', 'parents': [INBOX_FOLDER_ID]},
        fields='id'
    ).execute().get('id')
    
    # 親フォルダ取得
    file_meta = drive_service.files().get(fileId=file_id, fields='parents').execute()
    prev_parents = ",".join(file_meta.get('parents', []))
    
    # 更新実行
    drive_service.files().update(
        fileId=file_id,
        addParents=target_id,
        removeParents=prev_parents,
        body={'name': rename_to}
    ).execute()
    print(f"✅ Drive Updated: {rename_to}", flush=True)


# ==========================================
# Main Loop (原子性の保証)
# ==========================================

def main():
    print("--- SZ AUTO LOGGER ULTIMATE (v77.0) ---", flush=True)
    
    # スキャン
    files = drive_service.files().list(
        q=f"'{INBOX_FOLDER_ID}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
        fields="files(id, name)"
    ).execute().get('files', [])
    
    if not files:
        print("ℹ️ No files found.")
        return

    for file in files:
        try:
            print(f"\n📂 Processing: {file['name']}")
            fpath = os.path.join(TEMP_DIR, file['name'])
            
            # ダウンロード
            with open(fpath, "wb") as f:
                downloader = MediaIoBaseDownload(f, drive_service.files().get_media(fileId=file['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
            
            # --- [重要] 素材の純化 (Logic Filtering) ---
            audio_sources = []
            if file['name'].endswith('.zip'):
                with zipfile.ZipFile(fpath, 'r') as z:
                    z.extractall(TEMP_DIR)
                    for root, _, fs in os.walk(TEMP_DIR):
                        for af in fs:
                            # ゴミファイル(final_mix, chunk)やZIP自体を除外
                            lower = af.lower()
                            if lower.endswith(('.flac', '.mp3', '.m4a', '.wav')):
                                if 'final_mix' not in lower and 'chunk' not in lower:
                                    audio_sources.append(os.path.join(root, af))
            else:
                audio_sources.append(fpath)

            if not audio_sources:
                print("⚠️ No valid audio found (Skipping).")
                continue

            # --- 処理実行 ---
            mixed_mp3 = mix_audio_ffmpeg(audio_sources)
            chunk_paths = split_audio_ffmpeg(mixed_mp3)
            full_text = transcribe_with_groq(chunk_paths)
            meta, report, time_log = analyze_text_with_gemini(full_text)
            
            # --- 保存 ---
            dest_id, off_name = notion_query_student(meta.get('student_name', 'Unknown'))
            if not dest_id: dest_id = FINAL_FALLBACK_DB_ID
            
            props = {
                "名前": {"title": [{"text": {"content": f"{meta['date']} {off_name} ログ"}}]},
                "日付": {"date": {"start": meta['date']}}
            }
            
            content = f"### 📊 SZメソッド詳細分析\n\n{report}\n\n---\n### 📝 時系列ログ\n\n{time_log}"
            blocks = []
            for line in content.split('\n'):
                if line.strip():
                    blocks.append({
                        "object": "block", "type": "paragraph", 
                        "paragraph": {"rich_text": [{"text": {"content": line[:1900]}}]}
                    })
            
            notion_create_page_heavy(sanitize_id(dest_id), props, blocks)
            
            # --- 完了処理 ---
            ext = os.path.splitext(file['name'])[1] or ".zip"
            new_name = f"{meta.get('date', 'Unknown')}_{off_name}{ext}"
            cleanup_drive_file(file['id'], rename_to=new_name)

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            # [原子性] 毎回フォルダを消して次のループへ
            if os.path.exists(TEMP_DIR):
                shutil.rmtree(TEMP_DIR)
                os.makedirs(TEMP_DIR)

if __name__ == "__main__":
    main()
