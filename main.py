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
# Control Center (通知Bot実績ID)
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664"
# Fallback Inbox (生徒不明時の退避先)
FINAL_FALLBACK_DB_ID = "2b71bc8521e38018a5c3c4b0c6b6627c"

TEMP_DIR = "temp_workspace"
CHUNK_LENGTH = 900  # 15分 (秒) - Whisper API制限回避用

# --- Setup & Init ---
def setup_env():
    if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)
    
    # Generate SA Key for Google Drive
    if os.getenv("GCP_SA_KEY"):
        with open("service_account.json", "w") as f:
            f.write(os.getenv("GCP_SA_KEY"))

setup_env()

try:
    # Initialize Clients
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

    # Validate IDs
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    if not INBOX_FOLDER_ID: raise ValueError("DRIVE_FOLDER_ID is missing.")

except Exception as e:
    print(f"❌ Init Critical Error: {e}")
    sys.exit(1)

def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    if match: return match.group(1)
    return None

# --- Layer 1: FFmpeg Audio Processing (Memory Safe) ---

def run_ffmpeg(cmd):
    """Run FFmpeg command securely"""
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"⚠️ FFmpeg Error: {e}")
        raise

def mix_audio_ffmpeg(file_paths):
    """Mix multiple audio files into one lightweight MP3 using FFmpeg stream"""
    if not file_paths: return None
    print(f"🎛️ Mixing {len(file_paths)} tracks...", flush=True)
    
    output_path = os.path.join(TEMP_DIR, "mixed_full.mp3")
    
    inputs = []
    for f in file_paths: inputs.extend(['-i', f])
    
    # amix filter for mixing, output as 64k mono mp3 (sufficient for speech)
    if len(file_paths) > 1:
        filter_cmd = f"amix=inputs={len(file_paths)}:duration=longest"
        cmd = ['ffmpeg', '-y'] + inputs + ['-filter_complex', filter_cmd, '-ac', '1', '-b:a', '64k', output_path]
    else:
        cmd = ['ffmpeg', '-y', '-i', file_paths[0], '-ac', '1', '-b:a', '64k', output_path]
    
    run_ffmpeg(cmd)
    return output_path

def split_audio_ffmpeg(input_path):
    """Split large audio into small chunks to bypass API limits"""
    print("🔪 Splitting audio into chunks...", flush=True)
    output_pattern = os.path.join(TEMP_DIR, "chunk_%03d.mp3")
    
    # Split without re-encoding (-c copy) for speed
    cmd = [
        'ffmpeg', '-y', '-i', input_path, 
        '-f', 'segment', '-segment_time', str(CHUNK_LENGTH), 
        '-c', 'copy', output_pattern
    ]
    run_ffmpeg(cmd)
    chunks = sorted(glob.glob(os.path.join(TEMP_DIR, "chunk_*.mp3")))
    print(f"➡️ Created {len(chunks)} chunks.")
    return chunks

# --- Layer 2: Groq Transcription (Speed) ---

def transcribe_with_groq(chunk_paths):
    """Use Groq (Whisper Large V3) for lightning fast transcription"""
    full_transcript = ""
    print("🚀 Starting Groq Transcription...", flush=True)
    
    for i, chunk in enumerate(chunk_paths):
        print(f"   Processing chunk {i+1}/{len(chunk_paths)}...", flush=True)
        try:
            with open(chunk, "rb") as file:
                transcription = groq_client.audio.transcriptions.create(
                    file=(chunk, os.path.basename(chunk)),
                    model="whisper-large-v3",
                    language="ja",
                    response_format="text"
                )
                full_transcript += transcription + "\n"
        except Exception as e:
            print(f"⚠️ Groq Error on chunk {i+1}: {e}")
            full_transcript += f"\n[Error processing chunk {i+1}]\n"
            
    return full_transcript

# --- Layer 3: Gemini Analysis (Intelligence) ---

def analyze_text_with_gemini(transcript_text):
    """Analyze the raw text using Gemini 1.5 Flash"""
    print("🧠 Analyzing text with Gemini 1.5 Flash...", flush=True)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # Prompt adapted from v62.0 but optimized for TEXT input
    prompt = f"""
    あなたは**トップ・スマブラアナリスト**です。
    以下は、コーチ(Hikari)とクライアントの対話ログ（文字起こし済みテキスト）です。

    【指令】
    このテキストを分析し、以下の2つのセクションを出力してください。
    
    1. **詳細分析レポート**: 
       会話内で扱われた主要トピック（着地狩り、復帰阻止、メンタル等）を特定し、
       それぞれの「現状」「課題」「改善案」「やること」をMarkdown形式で詳述せよ。
    
    2. **JSONメタデータ**:
       生徒の名前、日付、次回の最重要アクションを抽出せよ。

    ---
    **[DETAILED_REPORT_START]**
    （ここに詳細レポートをMarkdownで見やすく記述）
    **[DETAILED_REPORT_END]**
    ---
    **[JSON_START]**
    {{
      "student_name": "生徒名（不明ならUnknown）",
      "date": "YYYY-MM-DD (不明ならToday)",
      "next_action": "最も重要な次回アクション"
    }}
    **[JSON_END]**
    ---

    【入力テキスト】
    {transcript_text[:1000000]}
    """
    
    response = model.generate_content(prompt, generation_config={"temperature": 0.2})
    text = response.text.strip()
    
    # Parse Logic
    report_match = re.search(r'\[DETAILED_REPORT_START\](.*?)\[DETAILED_REPORT_END\]', text, re.DOTALL)
    report_text = report_match.group(1).strip() if report_match else "分析レポート生成失敗"
    
    json_match = re.search(r'\[JSON_START\](.*?)\[JSON_END\]', text, re.DOTALL)
    data = {}
    if json_match:
        try:
            json_str = json_match.group(1).replace("```json", "").replace("```", "").strip()
            data = json.loads(json_str)
        except: pass
        
    if not data:
        data = {"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "Check Logs"}
    if data.get('date') in ['Unknown', 'Today', None]:
        data['date'] = datetime.now().strftime('%Y-%m-%d')
        
    return data, report_text

# --- Layer 4: Notion Database (Storage) ---

def notion_query_student(student_name):
    """Search for student ID in Control Center"""
    print(f"🔍 Looking up student: '{student_name}'", flush=True)
    if not FINAL_CONTROL_DB_ID: return None, student_name
    
    url = f"https://api.notion.com/v1/databases/{sanitize_id(FINAL_CONTROL_DB_ID)}/query"
    payload = {"filter": {"property": "Name", "title": {"contains": student_name}}}
    
    try:
        res = requests.post(url, headers=HEADERS, json=payload)
        data = res.json()
        if data.get("results"):
            row = data["results"][0]
            title_list = row["properties"].get("Name", {}).get("title", [])
            official_name = title_list[0]["plain_text"] if title_list else student_name
            target_id = row["properties"].get("TargetID", {}).get("rich_text", [])
            if target_id:
                return sanitize_id(target_id[0]["plain_text"]), official_name
    except Exception as e:
        print(f"⚠️ Notion Query Error: {e}")
        
    return None, student_name

def notion_append_children(block_id, children):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    # Chunk blocks into groups of 100
    for i in range(0, len(children), 100):
        chunk = children[i : i + 100]
        try:
            requests.patch(url, headers=HEADERS, json={"children": chunk})
            time.sleep(0.2) # Rate limit safety
        except Exception as e:
            print(f"⚠️ Append Error: {e}")

def notion_create_page_heavy(db_id, props, all_children):
    """Create page and append massive content safely"""
    url = "https://api.notion.com/v1/pages"
    
    # First 100 blocks
    initial_children = all_children[:100]
    remaining_children = all_children[100:]
    
    payload = {
        "parent": {"database_id": db_id},
        "properties": props,
        "children": initial_children
    }
    
    try:
        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()
        page_id = res.json()['id']
        print(f"✅ Page Created (ID: {page_id})", flush=True)
        
        if remaining_children:
            print(f"   Appending {len(remaining_children)} remaining blocks...", flush=True)
            notion_append_children(page_id, remaining_children)
            
    except Exception as e:
        print(f"❌ Notion Write Error: {e}")
        try: print(res.text)
        except: pass

# --- Drive Utilities ---

def download_file(file_id, file_name):
    request = drive_service.files().get_media(fileId=file_id)
    file_path = os.path.join(TEMP_DIR, file_name)
    with open(file_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
    return file_path

def cleanup_drive_file(file_id, rename_to=None):
    """処理済みファイルを移動し、必要ならリネームする"""
    folder_name = "processed_coaching_logs"
    try:
        # 1. 移動先フォルダの確保
        q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{INBOX_FOLDER_ID}' in parents and trashed=false"
        files = drive_service.files().list(q=q).execute().get('files', [])
        target_folder_id = files[0]['id'] if files else drive_service.files().create(
            body={'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [INBOX_FOLDER_ID]},
            fields='id'
        ).execute().get('id')
        
        # 2. 現在の親フォルダを取得
        file = drive_service.files().get(fileId=file_id, fields='parents').execute()
        previous_parents = ",".join(file.get('parents')) if file.get('parents') else ""

        # 3. 移動 & リネーム実行
        body = {}
        if rename_to:
            body['name'] = rename_to  # 新しいファイル名を設定
            
        drive_service.files().update(
            fileId=file_id,
            addParents=target_folder_id,
            removeParents=previous_parents,
            body=body,
            fields='id, parents, name'
        ).execute()
        
        log_msg = f" (Renamed to: {rename_to})" if rename_to else ""
        print(f"➡️ File moved to processed folder{log_msg}.", flush=True)

    except Exception as e:
        print(f"⚠️ Drive Cleanup Error: {e}", flush=True)

# --- Main Logic ---

def main():
    print("--- SZ AUTO LOGGER: ULTIMATE EDITION (v70.0) ---", flush=True)
    
    # 1. Drive Scan
    try:
        results = drive_service.files().list(
            q=f"'{INBOX_FOLDER_ID}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name)", orderBy="createdTime desc"
        ).execute()
        files = results.get('files', [])
    except Exception as e:
        print(f"❌ Drive Error: {e}")
        return

    if not files:
        print("ℹ️ No new files.", flush=True)
        return

    # 2. Manual Override Check
    manual_name = os.getenv("MANUAL_STUDENT_NAME")
    manual_target_id = None
    manual_official_name = None
    if manual_name:
        print(f"🔧 Manual Mode: {manual_name}")
        manual_target_id, manual_official_name = notion_query_student(manual_name)

    # 3. Processing Loop
    for file in files:
        print(f"\n📂 Processing: {file['name']}", flush=True)
        
        try:
            # Step A: Download & Extract
            file_path = download_file(file['id'], file['name'])
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

            if not audio_paths:
                print("⚠️ No audio found in file.")
                continue

            # Step B: FFmpeg Mix & Split (The "Heavy Lifting")
            mixed_file = mix_audio_ffmpeg(audio_paths)
            chunks = split_audio_ffmpeg(mixed_file)
            
            # Step C: Groq Transcription (The "Speedster")
            full_raw_text = transcribe_with_groq(chunks)
            if not full_raw_text.strip():
                print("❌ Transcription failed (Empty result).")
                continue

            # Step D: Gemini Analysis (The "Brain")
            meta_data, report_text = analyze_text_with_gemini(full_raw_text)
            
            # Step E: Target Resolution
            destination_id = FINAL_FALLBACK_DB_ID
            display_name = meta_data['student_name']
            log_suffix = f" (Unknown: {display_name})"
            
            # Priority: Manual > Auto-detected
            if manual_target_id:
                destination_id = manual_target_id
                display_name = manual_official_name
                log_suffix = ""
                print(f"🎯 Using Manual Target: {display_name}")
            else:
                auto_id, auto_name = notion_query_student(display_name)
                if auto_id:
                    destination_id = auto_id
                    display_name = auto_name
                    log_suffix = ""
                    print(f"🎯 Auto-detected Target: {display_name}")
            
            # Step F: Construct Notion Blocks
            props = {
                "名前": {"title": [{"text": {"content": f"{meta_data['date']} コーチングログ{log_suffix}"}}]},
                "日付": {"date": {"start": meta_data['date']}}
            }
            
            children = []
            # Report Section
            children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "📊 分析レポート"}}]}})
            for line in report_text.split('\n'):
                if line.strip():
                    children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": line[:2000]}}]}})
            
            # Next Action Section
            children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🚀 Next Action"}}]}})
            children.append({"object": "block", "type": "callout", "callout": {
                "rich_text": [{"text": {"content": meta_data.get('next_action', '-')}}],
                "icon": {"emoji": "🔥"}
            }})
            
            # Raw Transcript Section (Chunks of 2000 chars)
            children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "📝 全文文字起こし"}}]}})
            
            # テキストをブロックごとに安全に分割
            transcript_lines = full_raw_text.split('\n')
            current_chunk = ""
            for line in transcript_lines:
                if len(current_chunk) + len(line) < 1900:
                    current_chunk += line + "\n"
                else:
                    children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": current_chunk}}]}})
                    current_chunk = line + "\n"
            if current_chunk:
                children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": current_chunk}}]}})

            # Step G: Write to Notion
            notion_create_page_heavy(sanitize_id(destination_id), props, children)
            
            # Step H: Cleanup
           # 元の拡張子 (.zip など) を維持する
            original_ext = os.path.splitext(file['name'])[1]
            if not original_ext: original_ext = ".zip" # 万が一拡張子がない場合の保険
            
            # 新しい名前: "2025-12-23_らぎぴ.zip" のような形式
            new_filename = f"{meta_data['date']}_{display_name}{original_ext}"
            
            # 移動と同時にリネームを実行
            cleanup_drive_file(file['id'], rename_to=new_filename)
            
        except Exception as e:
            # ... (エラー処理はそのまま)
            
        except Exception as e:
            print(f"❌ Processing Failed for {file_name}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
            os.makedirs(TEMP_DIR)

if __name__ == "__main__":
    main()
