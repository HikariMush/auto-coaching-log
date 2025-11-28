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

# --- 最終設定（ハードコード） ---
# Control Center DBのID (通知Botで実績のあるIDを使用)
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664" 

# --- 初期化 ---
TEMP_DIR = "downloads"
if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
os.makedirs(TEMP_DIR)

if os.getenv("GCP_SA_KEY"):
    with open("service_account.json", "w") as f:
        f.write(os.getenv("GCP_SA_KEY"))

def sanitize_id(raw_id):
    # 厳密な正規表現チェックを外し、ハイフン除去のみに簡素化。
    if not raw_id: return "" # Noneではなく空文字列を返すことで、パスのNone挿入を防ぐ
    return raw_id.replace("-", "").strip() # ハイフンと外部スペースを除去

try:
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28" 
    }
    
    CONTROL_CENTER_ID = sanitize_id(FINAL_CONTROL_DB_ID)
    if not CONTROL_CENTER_ID:
        raise ValueError("CRITICAL: Final Control DB ID is empty after sanitization.")

    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
except Exception as e:
    print(f"❌ Setup Critical Error: {e}", flush=True)
    exit(1)

# --- Notion API 関数群 (Raw Requests) ---

def notion_query_database(db_id, query_filter):
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    try:
        res = requests.post(url, headers=HEADERS, json=query_filter)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.HTTPError as e:
        print(f"❌ Notion Query Error ({db_id}): Status {e.response.status_code}")
        print(f"   Detail: {e.response.text}")
        raise e

def notion_create_page(parent_db_id, properties, children):
    url = f"https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": parent_db_id},
        "properties": properties,
        "children": children
    }
    try:
        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.HTTPError as e:
        print(f"❌ Notion Create Page Error: Status {e.response.status_code}")
        print(f"   Detail: {e.response.text}")
        raise e

# --- Google Drive File Management (Omitted for brevity, fully included in file) ---

def get_or_create_processed_folder():
    """DriveのINBOX内に 'processed_coaching_logs' フォルダを探し、なければ作成する"""
    folder_name = "processed_coaching_logs"
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{INBOX_FOLDER_ID}' in parents and trashed=false"
    response = drive_service.files().list(q=query, fields='files(id)').execute()
    files = response.get('files', [])

    if files:
        return files[0]['id']
    else:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [INBOX_FOLDER_ID]
        }
        folder = drive_service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

def move_files_to_processed(file_ids, target_folder_id):
    """指定されたファイルを、現在のフォルダからターゲットフォルダへ移動する"""
    for file_id in file_ids:
        try:
            file = drive_service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents'))
            
            drive_service.files().update(
                fileId=file_id,
                addParents=target_folder_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()
            print(f"➡️ Moved file {file_id} to processed folder successfully.", flush=True)
        except Exception as e:
            print(f"❌ Failed to move file {file_id}. Error: {e}", flush=True)

# --- Audio/Drive/Gemini Helpers (Integration) ---

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
    print(f"🎛️ Mixing {len(file_paths)} audio tracks...", flush=True)
    try:
        mixed = AudioSegment.from_file(file_paths[0])
        for path in file_paths[1:]:
            track = AudioSegment.from_file(path)
            mixed = mixed.overlay(track)
        output_path = os.path.join(TEMP_DIR, "mixed_session.mp3")
        mixed.export(output_path, format="mp3")
        return output_path
    except Exception as e:
        print(f"⚠️ Mixing Error: {e}. Using largest file instead.", flush=True)
        return max(file_paths, key=os.path.getsize)

def get_available_model_name():
    print("🔍 Searching for highest available Pro model...", flush=True)
    models = list(genai.list_models())
    available_names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]

    for name in available_names:
        if 'gemini-2.5-pro' in name: return name 

    for name in available_names:
        if 'gemini-2.0-pro' in name: return name 
    
    for name in available_names:
        if 'gemini-2.5-flash' in name: return name
    for name in available_names:
        if 'gemini-2.0-flash' in name: return name
    
    return available_names[0] if available_names else 'models/gemini-2.0-flash'

def analyze_audio_auto(file_path):
    
    def generate_content_with_fallback(model_name, audio_file):
        """Quotaエラー時にモデルをFlashに切り替えて再試行する"""
        
        current_model_name = model_name
        for attempt in range(2): # 最大2回試行 (Pro -> Flash)
            try:
                print(f"🧠 Analyzing with model: {current_model_name} (Attempt {attempt+1})", flush=True)
                model = genai.GenerativeModel(current_model_name)
                
                # Content Generation
                response = model.generate_content([prompt, audio_file])
                
                return response.text
                
            except ResourceExhausted as e:
                if attempt == 0 and ("pro" in current_model_name.lower()):
                    current_model_name = 'gemini-2.5-flash'
                    print("⚠️ Quota Exceeded for Pro. Falling back to Flash model.", flush=True)
                    time.sleep(5) 
                    continue
                else:
                    raise e
            
            except Exception as e:
                raise e

        # fallback loop end

    model_name_initial = get_available_model_name()
    audio_file = genai.upload_file(file_path)
    while audio_file.state.name == "PROCESSING":
        time.sleep(2)
        audio_file = genai.get_file(audio_file.name)
    if audio_file.state.name == "FAILED": raise ValueError("Audio Failed")
    
    # Final Prompt (v47.1/v50.0)
    prompt = """
    あなたは**トップ・スマブラアナリスト**であり、具体的な課題を発見し解決するための**エージェント**です。
    この音声は、**コーチ (Hikari)** と **クライアント (生徒)** の対話ログです。

    【制約事項と文脈の優先度】
    1. **最優先ドメイン用語**: 「着地狩り」「崖際」「復帰阻止」「間合い」「確定反撃」などの専門用語を優先して正確に抽出せよ。
    2. **思考フレームワーク**: クライアントの発言と行動パターンを分析し、**認知バイアス**（例：現状維持バイアス）とゲーム内行動を紐づけて報告せよ。

    ---
    **[RAW_TRANSCRIPTION_START]**
    まず、会話全体を可能な限り正確に、逐語訳形式で文字起こしせよ。
    **[RAW_TRANSCRIPTION_END]**
    ---

    【コア分析構造：5要素抽出】
    上記の文字起こしに基づき、スマブラの内容および取り組み改善における話題は、以下の5要素に分割し、詳細な議事録として記録せよ。
    * **現状** (Current Status)
    * **課題** (Problem/Issue)
    * **原因** (Root Cause)
    * **改善案** (Proposed Solution)
    * **やること** (Next Action/Commitment)

    【最終出力形式】
    上記の詳細分析に基づき、最終的なコミットメントの記録として、以下のJSON構造のみを生成せよ。
    
    {
      "student_name": "生徒の名前（例: らぎぴ, トロピウス）",
      "date": "YYYY-MM-DD (不明ならToday)",
      "summary": "[感情アイコン] - セッションで特定されたコアな課題と、それを超えるための新しい**コミットメント**（150字以内）。",
      "next_action": "クライアントが具体的にコミットした、次のタスクと**期限（YYYY-MM-DDまたはN日後）**"
    }
    """
    
    response_text = generate_content_with_fallback(model_name_initial, audio_file)
    
    # 4. Cleanup and Parsing
    try: genai.delete_file(audio_file.name)
    except: pass

    text = response_text.strip()
    
    transcript_match = re.search(r'\[RAW_TRANSCRIPTION_START\](.*?)\[RAW_TRANSCRIPTION_END\]', text, re.DOTALL)
    raw_transcript = transcript_match.group(1).strip() if transcript_match else "ERROR: Raw transcript not found."
    
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match: 
        data = json.loads(json_match.group(0))
        
        if data.get('date') in ['Unknown', 'Today']:
            data['date'] = datetime.now().strftime('%Y-%m-%d')
        return data, raw_transcript 
    else: 
        raise ValueError("JSON Parse Failed")

# --- メイン処理 ---
def main():
    print("--- VERSION: AI OUTPUT LOGGING (v54.0) ---", flush=True)
    
    if not os.getenv("DRIVE_FOLDER_ID"):
        print("❌ Error: DRIVE_FOLDER_ID is missing!", flush=True)
        return

    # 1. Drive Search (Find unprocessed files)
    try:
        results = drive_service.files().list(
            q=f"'{INBOX_FOLDER_ID}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name, createdTime)",
            orderBy="createdTime desc"
        ).execute()
    except Exception as e:
        print(f"❌ Drive Search Error: {e}", flush=True)
        return
    
    files = results.get('files', [])
    
    if not files:
        print("ℹ️ No new files found. Exiting.", flush=True)
        return

    # 2. Manual Input Check
    manual_name = os.getenv("MANUAL_STUDENT_NAME")

    # 3. Main Processing Loop
    for file in files:
        file_id = file['id']
        file_name = file['name']
        
        try:
            print(f"\nProcessing File: {file_name}", flush=True)
            
            # 3.1. Audio Processing
            local_audio_paths = []
            path = download_file(file_id, file_name)
            if file_name.lower().endswith('.zip'):
                local_audio_paths.extend(extract_audio_from_zip(path))
            else:
                local_audio_paths.append(path)
            
            if not local_audio_paths:
                raise ValueError("No valid audio tracks found after extraction.")
            
            mixed_path = mix_audio_files(local_audio_paths)
            
            # 3.2. --- ★解析実行：JSONデータとRaw Transcriptの両方を取得★ ---
            full_analysis, raw_transcript = analyze_audio_auto(mixed_path)
            
            # --- ★新規機能：AI出力結果の実行ログ記録★ ---
            print("\n--- AI ANALYSIS OUTPUT (START) ---", flush=True)
            print(f"Student: {full_analysis.get('student_name', 'N/A')}", flush=True)
            print(f"Summary: {full_analysis.get('summary', 'N/A')}", flush=True)
            print(f"Next Action: {full_analysis.get('next_action', 'N/A')}", flush=True)
            print("\n[RAW TRANSCRIPT]", flush=True)
            print(raw_transcript, flush=True)
            print("--- AI ANALYSIS OUTPUT (END) ---\n", flush=True)
            # --- 記録終了 ---

            # 3.3. Name Logic
            final_student_name = manual_name if manual_name else full_analysis['student_name']
            print(f"ℹ️ Target Student for Lookup: '{final_student_name}'", flush=True)

            # --- 4. Notion Search and Write ---
            search_filter = {
                "filter": {
                    "property": "Name",
                    "title": { "contains": final_student_name } 
                }
            }
            
            cc_res_data = notion_query_database(CONTROL_CENTER_ID, search_filter)
            results_list = cc_res_data.get("results", [])
            
            if not results_list:
                print(f"❌ Error: Student '{final_student_name}' not found in Control Center. Skipping write.", flush=True)
                continue 

            # 5. Extract Target ID and Write
            target_id_prop = results_list[0]["properties"].get("TargetID", {}).get("rich_text", [])
            
            if not target_id_prop:
                print("❌ Error: TargetID is empty in Control Center. Skipping write.", flush=True)
                continue
            
            final_target_id = sanitize_id(target_id_prop[0]["plain_text"])

            if not final_target_id:
                print(f"❌ Error: TargetID for {final_student_name} is invalid.", flush=True)
                continue

            # 5.1. --- ★メインログ（要約）の作成と書き込み★ ---
            properties_summary = {
                "名前": {"title": [{"text": {"content": f"{full_analysis['date']} ログ (要約)"}}]},
                "日付": {"date": {"start": full_analysis['date']}}
            }
            children_summary = [
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": full_analysis['summary']}}]}},
                {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Next Action"}}]}},
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": full_analysis.get('next_action', 'なし')}}]}}
            ]
            notion_create_page(final_target_id, properties_summary, children_summary)
            print(f"✅ Summary Log written for {final_student_name}.", flush=True)

            
            # 5.2. --- ★新規機能：純粋な文字起こしログの作成と書き込み★ ---
            properties_transcript = {
                "名前": {"title": [{"text": {"content": f"{full_analysis['date']} ログ (全文)"}}]},
                "日付": {"date": {"start": full_analysis['date']}}
            }
            
            children_transcript = []
            if raw_transcript and raw_transcript != "ERROR: Raw transcript not found.":
                # 1行ずつブロックに変換
                for line in raw_transcript.split('\n'):
                    if line.strip(): 
                        children_transcript.append({
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {"rich_text": [{"text": {"content": line}}]}
                        })
            
            if children_transcript:
                notion_create_page(final_target_id, properties_transcript, children_transcript)
                print(f"✅ Full Transcript written for {final_student_name}.", flush=True)
            else:
                print("⚠️ Transcript was empty or not found. Skipping full text write.", flush=True)
                
            
            # 6. クリーンアップ
            processed_folder_id = get_or_create_processed_folder()
            move_files_to_processed([file_id], processed_folder_id)
            print(f"🎉 PROJECT SUCCESS: Completed processing for {final_student_name}.", flush=True)
            
       except Exception as e:
             print(f"❌ UNHANDLED CRASH IN LOOP: {e}", flush=True)
             import traceback
             traceback.print_exc()
        finally:
            if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
            os.makedirs(TEMP_DIR) 

if __name__ == "__main__":
    main()
