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

# --- Notion API Helpers ---

def notion_query_database(db_id, query_filter):
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    try:
        res = requests.post(url, headers=HEADERS, json=query_filter)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"⚠️ Notion Query Error: {e}")
        return None

def notion_create_page(parent_db_id, properties, children):
    url = "https://api.notion.com/v1/pages"
    # ブロック数が多すぎるとエラーになるため、100ブロックごとに分割して追加する処理が必要だが
    # ここでは簡易的に最初の100ブロックまでとする（または分割ロジックを追加）
    
    # 最初の作成リクエスト (Properties + 最初のChildren)
    initial_children = children[:90] # 安全マージン
    remaining_children = children[90:]
    
    payload = {"parent": {"database_id": parent_db_id}, "properties": properties, "children": initial_children}
    
    try:
        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()
        page_data = res.json()
        page_id = page_data['id']
        
        # 残りのブロックがある場合、Append APIで追加
        if remaining_children:
            append_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
            # 100個ずつループ
            for i in range(0, len(remaining_children), 100):
                chunk = remaining_children[i:i+100]
                requests.patch(append_url, headers=HEADERS, json={"children": chunk})
                
        return page_data
    except Exception as e:
        print(f"❌ Create Page Error: {e}")
        try: print(f"Detail: {res.text}")
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

def get_available_model_name():
    # ★FIX: Flash固定（トークン節約 & 高速化）
    print("🔍 Using Flash model (Efficiency Mode)...", flush=True)
    return 'models/gemini-2.0-flash'

def analyze_audio_auto(file_path):
    model_name = get_available_model_name()
    
    # ★FIX: 3部構成（文字起こし / 詳細レポート / JSONメタデータ）を出力させるプロンプト
    prompt = """
    あなたは**トップ・スマブラアナリスト**です。
    この音声は、**コーチ (Hikari)** と **クライアント (生徒)** の対話ログです。

    【最優先ドメイン用語】: 「着地狩り」「崖際」「復帰阻止」「間合い」「確定反撃」「ライン管理」「ベクトル変更」

    以下の3つのセクションを順に出力せよ。

    ---
    **[RAW_TRANSCRIPTION_START]**
    会話全体を、可能な限り詳細に、逐語訳に近い形で文字起こしせよ。
    （※出力が途切れないよう、フィラー「あー」「えー」などは適宜削除してよいが、内容は省略するな）
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

    try:
        print(f"🧠 Analyzing with {model_name}...", flush=True)
        model = genai.GenerativeModel(model_name)
        audio_file = genai.upload_file(file_path)
        while audio_file.state.name == "PROCESSING": time.sleep(2); audio_file = genai.get_file(audio_file.name)
        
        # 出力トークン最大化 (Flashは8192まで出せる)
        response = model.generate_content(
            [prompt, audio_file],
            generation_config=genai.types.GenerationConfig(max_output_tokens=8192)
        )
        text = response.text.strip()
        
        try: genai.delete_file(audio_file.name)
        except: pass

        # --- Parsing ---
        # 1. Raw Transcript
        raw_match = re.search(r'\[RAW_TRANSCRIPTION_START\](.*?)\[RAW_TRANSCRIPTION_END\]', text, re.DOTALL)
        raw_text = raw_match.group(1).strip() if raw_match else "Transcript Error"

        # 2. Detailed Report
        report_match = re.search(r'\[DETAILED_REPORT_START\](.*?)\[DETAILED_REPORT_END\]', text, re.DOTALL)
        report_text = report_match.group(1).strip() if report_match else "Report Error"

        # 3. JSON Metadata
        json_match = re.search(r'\[JSON_START\](.*?)\[JSON
