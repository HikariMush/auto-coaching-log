import os
import time
import json
import logging
import re
import zipfile
import shutil
from datetime import datetime
# from dotenv import load_dotenv # GitHub Actionsでは不要

# Google Libraries
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Audio & Notion
from pydub import AudioSegment
from notion_client import Client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- 定数・初期化 ---
TEMP_DIR = "downloads"
if os.path.exists(TEMP_DIR):
    shutil.rmtree(TEMP_DIR) # クリーンスタート
os.makedirs(TEMP_DIR)

# GitHub SecretsからJSONキーを復元
if os.getenv("GCP_SA_KEY"):
    with open("service_account.json", "w") as f:
        f.write(os.getenv("GCP_SA_KEY"))

try:
    notion = Client(auth=os.getenv("NOTION_TOKEN"))
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    
    # ★ここを修正しました (Pro -> Flash)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file(
        "service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    CONTROL_CENTER_ID = os.getenv("CONTROL_CENTER_ID")
    
except Exception as e:
    logging.error(f"Setup Error: {e}")
    exit(1)

# --- Drive操作関数 ---

def get_or_create_processed_folder():
    """処理済みフォルダのIDを取得、なければ作成"""
    query = f
