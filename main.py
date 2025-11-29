import os
import sys
import subprocess
import time
import json
import logging
import re
import zipfile
import shutil
from datetime import datetime

# --- ライブラリ強制セットアップ ---
try:
    import requests
    import google.generativeai as genai
    from pydub import AudioSegment
    from google.api_core.exceptions import ResourceExhausted
except ImportError:
    print("🔄 Installing core libraries...", flush=True)
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "--upgrade", 
        "requests", "google-generativeai>=0.8.3", "pydub",
        "google-api-python-client", "google-auth"
    ])
    import requests
    import google.generativeai as genai
    from pydub import AudioSegment
    from google.api_core.exceptions import ResourceExhausted

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- 最終設定 ---
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664" 

# --- 初期化 ---
TEMP_DIR = "downloads"
if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
os.makedirs(TEMP_DIR)

if os.getenv("GCP_SA_KEY"):
    with open("service_account.json", "w") as f:
        f.write(os.getenv("GCP_SA_KEY"))

def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    if match: return match.group(1)
    return None

try:
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28" 
    }
    
    CONTROL_CENTER_ID = sanitize_id(FINAL_CONTROL_DB_ID)
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
except Exception as e:
    print(f"❌ Setup Critical Error: {e}", flush=True)
    exit(1)

# --- Notion API Helpers (Raw Requests + Chunking) ---

def notion_query_database(db_id, query_filter):
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    try:
        res = requests.post(url, headers=HEADERS, json=query_filter)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"⚠️ Notion Query Error: {e}")
        return None

def notion_create_page_chunked(parent_db_id, properties, children):
    """
    Notionのブロック制限(100個)を回避するため、分割して書き込む関数
    """
    url = "https://api.notion.com/v1/pages"
    
    # 最初の90個（安全マージン）
    initial_children = children[:90]
    remaining_children = children[90:]
    
    payload = {
        "parent": {"database_id": parent_db_id},
        "properties": properties,
        "children": initial_children
    }
    
    try:
        # 1. ページ作成
        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()
        page_data = res.json()
        page_id = page_data['id']
        print("   ✅ Base page created. Appending remaining content...", flush=True)
        
        # 2. 残りのブロックを追記 (Append)
        if remaining_children:
            append_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
            
            # 100個ずつループ処理
            batch_size = 90
            for i in range(0, len(remaining_children), batch_size):
                chunk = remaining_children[i : i + batch_size]
                append_payload = {"children": chunk}
                
                append_res = requests.patch(append_url, headers=HEADERS, json=append_payload)
                if append_res.status_code != 200:
                    print(f"   ⚠️ Warning: Failed to append chunk {i}. Status: {append_res.status_code}", flush=True)
                else:
                    print(f"   ...Writing chunk {i} to {i+batch_size}", flush=True)
                
                time.sleep(0.5) # APIレート制限対策
                
        return page_data

    except requests.exceptions.HTTPError as e:
        print(f"❌ Create Page Error: {e.response.status_code}")
        try: print(f"   Detail: {e.response.text}")
        except: pass
        raise e

def get_student_target_id(student_name):
    print(f"🔍 Looking up student: '{student_name}'", flush=True)
    search_filter = {"filter": {"property": "Name", "title": {"contains": student_name}}}
    data = notion_query_database(CONTROL_CENTER_ID, search_filter)
    if not data or not data.get("results"): return None
    
    target_id_prop = data["results"][0]["properties"].get("TargetID", {}).get("rich_text", [])
    if not target_id_prop: return None
    return sanitize_id(target_id_prop[0]["plain_text"])

# --- Drive & Gemini Helpers ---

def download_file(file_id, file_name):
    request = drive_service.files().get_media(fileId=file_id)
    file_path = os.path.join(TEMP_DIR, file_name)
    with open(file_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
    return file_path

def extract_audio_from_zip(zip_path):
    extracted_files = []
    extract_dir = os.path.join(TEMP_DIR, "extracted_" + os.path.basename(zip_path))
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            if file.lower().endswith(('.flac', '.mp3', '.aac', '.wav', '.m4a')):
                extracted_files.append(os.path.join(root, file))
    return extracted_files

def mix_audio_files(file_paths):
    if not file_paths: return None
    print(f"🎛️ Mixing {len(file_paths)} tracks...", flush=True)
    try:
        mixed = AudioSegment.from_file(file_paths[0])
        for path in file_paths[1:]:
            mixed = mixed.overlay(AudioSegment.from_file(path))
        output_path = os.path.join(TEMP_DIR, "mixed_session.mp3")
        mixed.export(output_path, format="mp3")
        return output_path
    except Exception as e:
        print(f"⚠️ Mixing Error: {e}. Using largest file.", flush=True)
        return max(file_paths, key=os.path.getsize)

def analyze_audio_auto(file_path):
    # Flashモデル固定 (Resource Efficiency)
    model_name_initial = 'models/gemini-2.0-flash'
    
    # ★完全版プロンプト（文字起こし＋詳細レポート＋JSON）
    prompt = """
    あなたは**トップ・スマブラアナリスト**であり、行動経済学に基づく課題解決エージェントです。
    この音声は、**コーチ (Hikari)** と **クライアント (生徒)** の対話ログです。

    【最優先ドメイン用語】: 「着地狩り」「着地」「崖上がり」「崖狩り」「見てから」「読みで」「復帰」「崖際」「復帰阻止」「間合い」「確定反撃」「ライン管理」「ベクトル変更」「暴れ」

    以下の3つのセクションを、**区切りタグを含めて**順に出力せよ。

    ---
    **[RAW_TRANSCRIPTION_START]**
    会話全体を、可能な限り詳細に、逐語訳に近い形で文字起こしせよ。
    （※出力が途切れないよう、フィラー「あー」「えー」などは適宜削除してよいが、重要な内容は省略するな）
    **[RAW_TRANSCRIPTION_END]**
    ---
    **[DETAILED_REPORT_START]**
    会話内で扱われた各トピックについて、以下の**5要素**を用いて詳細に分解・解説せよ。
    文字数制限は設けない。具体的かつ論理的に記述すること。
    Markdown形式（見出しや箇条書き）を使用せよ。

    ### トピック1: [トピック名]
    * **現状**: [具体的な現状]
    * **課題**: [発見された課題]
    * **原因**: [根本原因、認知バイアスなど]
    * **改善案**: [提示された解決策]
    * **やること**: [具体的なアクション]

    ### トピック2: [トピック名]
    ...（以降、トピックがある限り繰り返す）
    **[DETAILED_REPORT_END]**
    ---
    **[JSON_START]**
    以下のJSONデータのみを記述せよ。
    {
      "student_name": "生徒の名前（例: らぎぴ, トロピウス, Unknown）",
      "date": "YYYY-MM-DD (不明ならToday)",
      "next_action": "最も重要な次回のアクション（1行）"
    }
    **[JSON_END]**
    """

    current_model = model_name_initial
    for attempt in range(2):
        try:
            print(f"🧠 Analyzing with {current_model}...", flush=True)
            model = genai.GenerativeModel(current_model)
            audio_file = genai.upload_file(file_path)
            
            while audio_file.state.name == "PROCESSING":
                time.sleep(2)
                audio_file = genai.get_file(audio_file.name)
            if audio_file.state.name == "FAILED": raise ValueError("Audio Failed")
            
            # Max tokens for Flash (8192)
            response = model.generate_content(
                [prompt, audio_file],
                generation_config=genai.types.GenerationConfig(max_output_tokens=8192)
            )
            text = response.text.strip()
            
            try: genai.delete_file(audio_file.name)
            except: pass

            # --- Parsing Logic ---
            # 1. Raw Transcript
            raw_match = re.search(r'\[RAW_TRANSCRIPTION_START\](.*?)\[RAW_TRANSCRIPTION_END\]', text, re.DOTALL)
            raw_text = raw_match.group(1).strip() if raw_match else "Transcript Error/Truncated"

            # 2. Detailed Report
            report_match = re.search(r'\[DETAILED_REPORT_START\](.*?)\[DETAILED_REPORT_END\]', text, re.DOTALL)
            report_text = report_match.group(1).strip() if report_match else "Report Error/Truncated"

            # 3. JSON Metadata
            json_match = re.search(r'\[JSON_START\](.*?)\[JSON_END\]', text, re.DOTALL)
            
            data = {}
            if json_match:
                try:
                    json_str = json_match.group(1).replace("```json", "").replace("```", "").strip()
                    data = json.loads(json_str)
                except:
                    print("⚠️ JSON parse error. Using fallback.", flush=True)
                    data = {}
            
            if not data:
                data = {"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "解析失敗/要確認"}
            
            if data.get('date') in ['Unknown', 'Today', None]:
                data['date'] = datetime.now().strftime('%Y-%m-%d')
                
            return data, raw_text, report_text

        except ResourceExhausted:
            if attempt == 0:
                print("⚠️ Quota Exceeded. Waiting 10s and retrying...", flush=True)
                time.sleep(10)
                continue
            raise

        except Exception as e:
            print(f"❌ AI Error: {e}", flush=True)
            raise e

# --- File Cleanup ---
def cleanup_drive_file(file_id):
    folder_name = "processed_coaching_logs"
    try:
        q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{INBOX_FOLDER_ID}' in parents and trashed=false"
        res = drive_service.files().list(q=q, fields='files(id)').execute()
        files = res.get('files', [])
        target_id = files[0]['id'] if files else drive_service.files().create(body={'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [INBOX_FOLDER_ID]}, fields='id').execute().get('id')
        
        file = drive_service.files().get(fileId=file_id, fields='parents').execute()
        drive_service.files().update(fileId=file_id, addParents=target_id, removeParents=",".join(file.get('parents')), fields='id, parents').execute()
        print("➡️ File moved to processed folder.", flush=True)
    except: pass

# --- Main Logic ---
def main():
    print("--- VERSION: FINAL ROBUST BUILD (v61.0) ---", flush=True)
    
    if not INBOX_FOLDER_ID: return

    # 1. Drive Check
    try:
        results = drive_service.files().list(
            q=f"'{INBOX_FOLDER_ID}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name)", orderBy="createdTime desc"
        ).execute()
    except Exception as e:
        print(f"❌ Drive Search Error: {e}", flush=True)
        return
    
    files = results.get('files', [])
    if not files:
        print("ℹ️ No new files found.", flush=True)
        return

    # 2. Manual Mode Check
    manual_name = os.getenv("MANUAL_STUDENT_NAME")
    manual_target_id = None
    
    if manual_name:
        print(f"✅ Manual Mode: Checking '{manual_name}'...", flush=True)
        manual_target_id = get_student_target_id(manual_name)
        if not manual_target_id:
            print(f"❌ Error: '{manual_name}' not found in Control Center. Fallback to Auto.", flush=True)
            manual_name = None

    # 3. Processing Loop
    for file in files:
        file_id = file['id']
        file_name = file['name']
        print(f"\nProcessing File: {file_name}", flush=True)
        
        try:
            # 3.1 Audio Prep
            local_audio_paths = [] # ★修正: 変数名の初期化
            
            path = download_file(file_id, file_name)
            if file_name.lower().endswith('.zip'):
                local_audio_paths.extend(extract_audio_from_zip(path))
            else:
                local_audio_paths.append(path)
            
            if not local_audio_paths: # ★修正: 正しい変数をチェック
                print("⚠️ No audio tracks found. Skipping.", flush=True)
                continue
                
            mixed_path = mix_audio_files(local_audio_paths)

            # 3.2 AI Analysis
            json_meta, raw_transcript, detailed_report = analyze_audio_auto(mixed_path)
            
            # 3.3 Destination Logic
            final_target_id = None
            student_name = json_meta.get('student_name', 'Unknown')

            if manual_target_id:
                final_target_id = manual_target_id
                student_name = manual_name
                print(f"📝 Using Manual Target ID for: {student_name}", flush=True)
            else:
                final_target_id = get_student_target_id(student_name)
            
            if not final_target_id:
                print(f"❌ Critical: Destination not found for '{student_name}'. Skipping.", flush=True)
                continue

            # 3.4 Write to Notion (Merged Page with Chunks)
            
            props = {
                "名前": {"title": [{"text": {"content": f"{json_meta['date']} コーチングログ"}}]},
                "日付": {"date": {"start": json_meta['date']}}
            }
            
            # コンテンツ構築
            children_blocks = []
            
            # (A) 詳細分析レポート
            children_blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "📊 詳細分析レポート"}}]}})
            for line in detailed_report.split('\n'):
                if line.strip():
                    children_blocks.append({
                        "object": "block", "type": "paragraph", 
                        "paragraph": {"rich_text": [{"text": {"content": line[:2000]}}]}
                    })

            # (B) Next Action
            children_blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🚀 Next Action"}}]}})
            children_blocks.append({"object": "block", "type": "callout", "callout": {"rich_text": [{"text": {"content": json_meta.get('next_action', 'なし')}}]}})

            # (C) 全文文字起こし
            children_blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "📝 全文文字起こし"}}]}})
            for line in raw_transcript.split('\n'):
                if line.strip():
                    children_blocks.append({
                        "object": "block", "type": "paragraph",
                        "paragraph": {"rich_text": [{"text": {"content": line[:2000]}}]}
                    })

            # 書き込み実行 (分割対応)
            notion_create_page_chunked(final_target_id, props, children_blocks)
            print("✅ Log created successfully.", flush=True)

            # 3.5 Cleanup
            cleanup_drive_file(file_id)

        except Exception as e:
            print(f"❌ Error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
            os.makedirs(TEMP_DIR)

if __name__ == "__main__":
    main()
