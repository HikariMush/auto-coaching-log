import sys
import subprocess
import os
import time
import json
import shutil
import glob
import re
import traceback
import copy
import difflib
from datetime import datetime, timedelta, timezone

# --- 0. SDK & Tools ---
def install_package(package):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except: pass

install_package("google-genai")
install_package("groq")
install_package("patool")

# --- Libraries ---
import requests
from google import genai 
from google.genai import types
from groq import Groq
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from googleapiclient.errors import HttpError
import patoolib

# --- Configuration ---
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664"
FINAL_FALLBACK_DB_ID = "2e01bc8521e380ffaf28c2ab9376b00d"
TEMP_DIR = "temp_workspace"
CHUNK_LENGTH = 900  # 15 min

# Global Variables
RESOLVED_MODEL_ID = None
BOT_EMAIL = None
STUDENT_REGISTRY = {}
COMMON_TERMS = ""

# Try to load glossary
try:
    from smash_glossary import COMMON_TERMS
except ImportError:
    pass

# --- Helper: Verbose Error Printer ---
def log_error(context, error_obj):
    if isinstance(error_obj, HttpError) and "storageQuotaExceeded" in str(error_obj):
        print(f"⚠️ [Quota Limit] Could not upload artifact ({context}). Skipping.", flush=True)
    else:
        print(f"\n❌ [ERROR] {context}", flush=True)
        print(f"   Details: {str(error_obj)}", flush=True)
        print("-" * 30, flush=True)

# --- 1. Model Selection Logic (Dynamic & Strict) ---

def parse_model_score(model_name):
    """
    モデル名からバージョンとティアを解析し、スコア化する。
    戻り値: (version_float, tier_score)
    """
    # Version extraction (e.g., gemini-1.5-pro -> 1.5)
    ver_match = re.search(r"gemini-(\d+\.\d+)", model_name)
    version = float(ver_match.group(1)) if ver_match else 0.0
    
    # Tier scoring
    tier = 0
    if "ultra" in model_name: tier = 5
    elif "thinking" in model_name: tier = 4.5 # Thinking models often outperform Pro
    elif "pro" in model_name: tier = 4
    elif "flash" in model_name: tier = 2
    elif "nano" in model_name: tier = 1
    
    # Experimental penalty/bonus? 
    # Current stance: Use Exp if it's the highest version available. No penalty.
    
    return version, tier

def fetch_and_rank_models(client):
    print("📡 Fetching available models from API...", flush=True)
    try:
        # SDKの仕様に合わせてモデルリストを取得
        # google-genai SDK v0.1+ uses client.models.list()
        all_models = list(client.models.list())
        
        candidates = []
        print(f"🔍 Found {len(all_models)} total models. Filtering...", flush=True)

        for m in all_models:
            # modelオブジェクトから名前を取得 (m.name or m.display_name depending on SDK version)
            m_name = m.name.replace("models/", "") if hasattr(m, "name") else str(m)
            
            # 基本フィルタ: generateContentが使えるGemini系モデルのみ
            if "gemini" not in m_name or "vision" in m_name: 
                continue
            
            version, tier = parse_model_score(m_name)
            
            # --- STRICT THRESHOLD CHECK ---
            # 下限: 2.5 Pro (Version >= 2.5 AND Tier >= Pro(4))
            # ただし、Version 3.0 Flash (Ver=3.0, Tier=2) は 2.5 Proより賢い可能性が高いため、
            # 「Versionが2.5より大きければFlashでも可」とするか、
            # ユーザー指示通り「2.5Proが下限」を厳密に守るか。
            # 指示：能力の下限が2.5Pro。
            # 解釈：Version 2.5以上は必須。Version 2.5の場合はPro以上必須。
            
            is_qualified = False
            if version > 2.5:
                is_qualified = True # 3.0 Flash etc are OK
            elif version == 2.5:
                if tier >= 4: # Pro, Thinking, Ultra
                    is_qualified = True
            
            if is_qualified:
                candidates.append({
                    "id": m_name,
                    "version": version,
                    "tier": tier,
                    "score": version * 10 + tier # Weight version heavily
                })
        
        # Sort by Score Descending
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    except Exception as e:
        print(f"❌ Failed to list models: {e}")
        return []

def setup_env_and_model():
    global RESOLVED_MODEL_ID, BOT_EMAIL
    if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)
    
    # --- GCP Setup ---
    sa_key = os.getenv("GCP_SA_KEY")
    if sa_key:
        with open("service_account.json", "w") as f: f.write(sa_key)
        try:
            key_data = json.loads(sa_key)
            BOT_EMAIL = key_data.get("client_email", "Unknown")
        except: pass
    else:
        print("❌ ENV Error: GCP_SA_KEY missing.")
        sys.exit(1)

    # --- Model Selection ---
    try:
        gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        
        # 1. Get Ranked Candidates
        candidates = fetch_and_rank_models(gemini_client)
        
        if not candidates:
            print("❌ CRITICAL: No models found meeting the minimum criteria (>= 2.5 Pro).")
            print("   Please check your API Key permissions or wait for model release.")
            sys.exit(1)

        print(f"📋 Candidate List (Top 5): {[c['id'] for c in candidates[:5]]}", flush=True)

        # 2. Test Candidates in Order
        for cand in candidates:
            mid = cand["id"]
            print(f"👉 Testing Candidate: [{mid}]...", flush=True)
            try:
                # Ping test
                gemini_client.models.generate_content(model=mid, contents="Test.")
                print(f"✅ LOCKED: Using [{mid}] (Ver: {cand['version']}, Tier: {cand['tier']})", flush=True)
                RESOLVED_MODEL_ID = mid
                break
            except Exception as e:
                print(f"   ⚠️ Failed ({mid}): {e}")
                continue
        
        if not RESOLVED_MODEL_ID:
            print("❌ CRITICAL: All qualified models failed connectivity checks.")
            sys.exit(1)

    except Exception as e:
        log_error("Model Setup Failed", e)
        sys.exit(1)

    # --- Other Services ---
    global groq_client, drive_service, INBOX_FOLDER_ID, HEADERS
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=['https://www.googleapis.com/auth/drive'])
    drive_service = build('drive', 'v3', credentials=creds)
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")

# --- Execute Setup ---
setup_env_and_model()


def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    return match.group(1) if match else None

# --- Logic: Registry & Fuzzy Match ---

def load_student_registry():
    global STUDENT_REGISTRY
    print("📋 Loading Student Registry from Notion...", flush=True)
    db_id = sanitize_id(FINAL_CONTROL_DB_ID)
    if not db_id: return

    has_more = True
    next_cursor = None
    count = 0

    while has_more:
        payload = {"page_size": 100}
        if next_cursor: payload["start_cursor"] = next_cursor
        
        try:
            res = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query", headers=HEADERS, json=payload)
            if res.status_code != 200: break
            data = res.json()
            for row in data.get("results", []):
                try:
                    name_list = row["properties"]["Name"]["title"]
                    if not name_list: continue
                    name = name_list[0]["plain_text"]
                    tid_list = row["properties"]["TargetID"]["rich_text"]
                    tid = sanitize_id(tid_list[0]["plain_text"]) if tid_list else None
                    if name and tid:
                        STUDENT_REGISTRY[name] = tid
                        count += 1
                except: continue
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
        except Exception as e: break
    print(f"✅ Loaded {count} students into registry.", flush=True)

def find_best_student_match(query_name):
    if not query_name or not STUDENT_REGISTRY: return None, query_name
    if query_name in STUDENT_REGISTRY: return STUDENT_REGISTRY[query_name], query_name
    matches = difflib.get_close_matches(query_name, list(STUDENT_REGISTRY.keys()), n=1, cutoff=0.4)
    if matches:
        print(f"🎯 Fuzzy Match: '{query_name}' -> '{matches[0]}'", flush=True)
        return STUDENT_REGISTRY[matches[0]], matches[0]
    return None, query_name

# --- Logic: Metadata Helpers ---

def sanitize_filename(filename):
    return filename.replace("/", "_").replace("\\", "_")

def get_jst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def extract_date_smart(filename, drive_created_time_iso):
    match = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{1,2}-\d{1,2}-\d{1,2})', filename)
    if match:
        d_part = match.group(1)
        t_part = match.group(2).replace('-', ':')
        t_parts = t_part.split(':')
        t_formatted = f"{int(t_parts[0]):02}:{int(t_parts[1]):02}:{int(t_parts[2]):02}"
        return f"{d_part} {t_formatted}", d_part
    
    if drive_created_time_iso:
        try:
            dt = datetime.fromisoformat(drive_created_time_iso.replace('Z', '+00:00'))
            dt_jst = dt.astimezone(timezone(timedelta(hours=9)))
            return dt_jst.strftime('%Y-%m-%d %H:%M:%S'), dt_jst.strftime('%Y-%m-%d')
        except: pass

    now_jst = get_jst_now()
    return now_jst.strftime('%Y-%m-%d %H:%M:%S'), now_jst.strftime('%Y-%m-%d')

def detect_student_candidate_raw(file_list, original_archive_name):
    """
    ファイル名の一部が、Notionデータベース（STUDENT_REGISTRY）の登録名に含まれているかを厳密にチェックする。
    例: ファイル名 '2-kiyamu.flac' (clean: kiyamu) -> DB名 'キャム kiyamu' に包含されるためヒット。
    """
    global STUDENT_REGISTRY
    
    ignore_files = ["raw.dat", "info.txt", "ds_store", "thumbs.db", "desktop.ini", "readme", "license"]
    # hikariはコーチ（User）のため、候補から除外
    ignore_names = ["hikari", "craig", "entrymonster", "bot", "ssb", "recording"] 

    potential_candidates = []

    print("🔎 Scanning internal files for registry match...", flush=True)
    
    # 1. ファイルリストから候補文字列を抽出
    for f in file_list:
        basename = os.path.basename(f).lower()
        if any(ign in basename for ign in ignore_files): continue
        
        name_part = os.path.splitext(basename)[0]
        # "1-name", "2_name" などのプレフィクスを除去
        clean_name = re.sub(r'^\d+[-_]?', '', name_part)
        
        if any(ign in clean_name for ign in ignore_names): continue
        if len(clean_name) < 2: continue
        
        potential_candidates.append(clean_name)

    # 2. アーカイブ自体のファイル名も候補に加える
    base_archive = os.path.basename(original_archive_name)
    archive_clean = re.sub(r'\.zip|\.flac|\.mp3|\.wav', '', base_archive, flags=re.IGNORECASE)
    archive_clean = re.sub(r'\d{4}-\d{2}-\d{2}', '', archive_clean).strip()
    if len(archive_clean) > 2:
        potential_candidates.append(archive_clean)

    # 3. データベース（Registry）との厳密な包含チェック
    # ファイル名文字列(candidate) が DB名(db_name) に含まれているかを確認
    if STUDENT_REGISTRY:
        for candidate in potential_candidates:
            cand_lower = candidate.lower()
            for db_name in STUDENT_REGISTRY.keys():
                # Registryキー（例: "キャム kiyamu"）の中に候補（"kiyamu"）が含まれるか
                if cand_lower in db_name.lower():
                    print(f"💡 Registry Match Found: File '{candidate}' matches DB '{db_name}'", flush=True)
                    return db_name

    # 4. マッチしなかった場合、Geminiへのヒントとして候補文字列をそのまま返す（レガシー挙動）
    if potential_candidates:
        fallback = potential_candidates[0]
        print(f"⚠️ No direct registry match. Using raw hint: {fallback}", flush=True)
        return fallback

    return None

# --- 3. Audio Pipeline ---

def run_ffmpeg_command(cmd, task_name):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"\n❌ FFmpeg Error during '{task_name}':\n{e.stderr}", flush=True)
        raise e

def mix_audio_ffmpeg(file_paths):
    print(f"🎛️ Mixing {len(file_paths)} tracks...", flush=True)
    output_path = os.path.abspath(os.path.join(TEMP_DIR, "final_mix.mp3"))
    inputs = []
    valid_files = [f for f in file_paths if f.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.aac'))]
    if not valid_files: raise Exception("No audio files.")
    for f in valid_files: inputs.extend(['-i', f])
    filter_part = ['-filter_complex', f'amix=inputs={len(valid_files)}:duration=longest'] if len(valid_files) > 1 else []
    cmd = ['ffmpeg', '-y'] + inputs + filter_part + ['-ac', '1', '-b:a', '64k', output_path]
    run_ffmpeg_command(cmd, "Mixing Audio")
    return output_path

def split_audio_ffmpeg(input_path):
    print("🔪 Splitting...", flush=True)
    output_pattern = os.path.join(TEMP_DIR, "chunk_%03d.mp3")
    cmd = ['ffmpeg', '-y', '-i', input_path, '-f', 'segment', '-segment_time', str(CHUNK_LENGTH), '-ac', '1', '-b:a', '64k', output_pattern]
    run_ffmpeg_command(cmd, "Splitting Audio")
    return sorted(glob.glob(os.path.join(TEMP_DIR, "chunk_*.mp3")))

def transcribe_with_groq(chunk_paths):
    full_transcript = ""
    for chunk in chunk_paths:
        if not chunk.endswith(".mp3"): continue
        print(f"🚀 Groq Transcribing: {os.path.basename(chunk)}", flush=True)
        max_retries = 50
        for attempt in range(max_retries):
            try:
                with open(chunk, "rb") as file:
                    res = groq_client.audio.transcriptions.create(
                        file=(os.path.basename(chunk), file),
                        model="whisper-large-v3", language="ja", response_format="text"
                    )
                full_transcript += res + "\n"
                break 
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "rate limit" in err_str:
                    wait = 70
                    print(f"⏳ Groq Limit. Waiting {wait}s... ({attempt+1}/{max_retries})", flush=True)
                    time.sleep(wait)
                else: 
                    log_error("Groq Transcription Failed", e)
                    raise e
        else: raise Exception("❌ Groq Rate Limit persists. Aborting.")
    return full_transcript

# --- 4. Intelligence Analysis (Dynamic Expert Mode) ---

def analyze_text_with_gemini(transcript_text, date_hint, raw_name_hint):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY")) # Re-init to be safe
    print(f"🧠 Gemini Analyzing using [{RESOLVED_MODEL_ID}]...", flush=True)
    
    hint_context = f"録音日時: {date_hint}"
    if raw_name_hint:
        hint_context += f"\n【重要】ファイル名ヒント: '{raw_name_hint}' (これを最優先で生徒名として採用せよ)"
    
    glossary_instruction = ""
    if COMMON_TERMS:
        glossary_instruction = f"\n【重要参照：スマブラ用語集】\n誤字訂正用辞書です。以下の定義に基づき専門用語を補正せよ。\n{COMMON_TERMS}\n"

    # ★ V130.1 PROMPT (High-Fidelity Logic Extraction - FULL)
    prompt = f"""
    あなたは論理的な書記官であり、構造化のスペシャリストです。
    提供された会話データ（指導ログ）から、指導内容を忠実に抽出し、Notion用のレポートを作成してください。

    【メタデータ情報】
    {hint_context}
    {glossary_instruction}

    【重要：分析・出力の絶対制約】
    1. **事実への忠実性 (No Hallucination):**
       - 会話に含まれていない「褒め言葉」や「感情的表現」をAIが勝手に創作することを厳禁とする。
       - 会話に含まれていない「最悪の未来（負ける、引退するなど）」を勝手に予測・記述することを厳禁とする。
       - あくまで「会話の中で実際に指摘された論理」のみを構造化せよ。

    2. **解釈の禁止:**
       - 曖昧な発言を無理にポジティブ/ネガティブに解釈せず、発言の意図（ロジック）をそのまま記述せよ。
       - 指導者が「良い」と言った箇所のみを「良い点」とし、「直すべき」と言った箇所のみを「課題」とせよ。

    【重要参照：カテゴリ定義】
    レポートの「トピック名」を決定する際は、以下の定義に最も合致するものを選べ。
    **技術面（1-10）と、プレイヤー面（11-13）を明確に区別すること。また、同一番号の話題でも複数個のトピックの話が出ている場合は、分けること。例：着地狩り文脈で、回避着地を狩れていないこと、と、相手がジャンプした先を追う動きが出来ていない、があった場合は、別々に分解する必要がある。**

    -- ゲーム内技術 (In-Game) --
    1. **差し合い:** お互いが地上または空中にいて、有利不利がない状態。技の当て合い。
    2. **着地:** 【守り】自分が空中にいて、ステージに戻ろうとしている状態。
    3. **着地狩り:** 【攻め】相手が浮いていて、それを追撃している状態。
    4. **復帰:** 【守り】自分がステージ外に飛ばされ、崖やステージ上に戻ろうとしている状態。
    5. **復帰阻止:** 【攻め】相手がステージ外にいて、戻ってくるところを阻止・撃墜しようとする状態。
    6. **崖上がり:** 【守り】自分が崖に掴まっている状態から、ライン復帰を目指す状態。
    7. **崖狩り:** 【攻め】相手が崖に掴まっていて、その上がり際を狩ろうとする状態。
    8. **ダウン狩り/受け身:** 相手または自分がダウン（転倒）した際の攻防。
    9. **撃墜:** 上記フェーズの中で、特に「相手をバーストすること」に特化した議論。
    10. **撃墜拒否:** 上記フェーズの中で、特に「自分がバーストされないこと」に特化した議論。

    -- プレイヤー管理 (Meta-Game) --
    11. **マインドセット:** 試合中のメンタル制御、緊張、怒り、自信、大会への心構えなど。
    12. **体調管理:** 睡眠、食事、目の疲れ、姿勢、カフェイン摂取、生活リズムなど、肉体的なコンディション。
    13. **取り組み/座学:** 練習メニュー、リプレイ分析の質、目標設定、スケジューリング、学習プロセス全般。

    ---
    **【重要：出力レイアウト規則】**
    * Notionで見やすい階層構造を作ること。
    * **構造:**
        * トピック名: `##` (H2) ※上記のカテゴリ定義から選択すること。
        * 詳細項目の見出し: `###` (H3) ※箇条書きのリスト記号(-)や太字(**)は使わず、シンプルに見出しにする。
    * **余白:** 各項目の間には必ず「空行」を入れること。

    **【Section 1: 詳細分析レポート】**
    会話データから主要な改善ポイントを抽出し、各トピックについて以下の3つの観点を必ず網羅して記述せよ。省略は許されない。

    ## [カテゴリ名: 具体的な内容] (例: ## 体調管理: 大会前の睡眠リズム)

    ### ① 現状の挙動 (Fact)
    プレイヤーがどのような動きをしていたか、あるいはどのような認識を持っていたか。
    会話内で言及された事実のみを記述する。
    ※指導者が肯定的に評価した部分があれば、ここに「評価点」として記載する。（無ければ記載しないこと）

    ### ② 指摘事項 (Logic)
    その挙動に対して、どのような修正指示や論理的指摘が入ったか。
    「なぜそれがダメなのか」「どうあるべきか」という指導者のロジックを簡潔にまとめる。

    ### ③ 改善アクション (Action)
    具体的にどう動くべきか、何を意識すべきか。

    **【Section 2: 課題セット】**
    課題を箇条書きせよ。省略は許されない。
    フォーマットに関して、技術面(1~10)の場合は、
    「状況(距離&タイミング&その他情報に言及)」→「正解行動(キャラの動き + 脳の動き)」の形。行動が２段階に分かれている場合はそれも記載する。

    例:
    着地狩り 急降下回避着地狩り
    状況：相手大ジャンプ1個分上 相手ジャンプなし
    正解：引きステ(暴れケア) + 暴れ&回避確認 → DA差し返し or 横スマ

    プレイヤー面(11~13)の場合は「トリガー(事象)」→「アクション(対処)」とする。

    **【Section 3: 時系列ログ】**
    セッションの流れを時系列で要約せよ。

    **【Section 4: メタデータJSON】**
    {{
      "student_name": "生徒名",
      "date": "YYYY-MM-DD",
      "next_action": "最優先アクション"
    }}

    **【Section 5: 思考フローチャート (Mermaid)】**
    Section 1で分析した「判断の分岐」や「改善アクションのプロセス」を、Mermaid記法（flowchart TD）で視覚化せよ。
    
    **＜Mermaid作成の絶対ルール（エラー防止）＞**
    1. **構文:** `graph TD` を使用する。
    2. **禁止文字:** ダブルクォーテーション `"`、**半角コンマ `,`**、**半角カッコ `()`** は絶対に禁止。
    3. **代替文字:** 句読点は全角の `、` `。` を、カッコは全角の `（` `）` を使用せよ。
    4. **内容:** 単なる項目の羅列ではなく、**「Check（判断）」→「Branch（分岐）」→「Action（行動）」**の流れを描くこと。
    5. **形状:** 判断/分岐にはひし形 {{ }}、処理/行動には四角 [ ] を正しく使い分けること。

    ---
    **出力ブロック（システム制御用タグ）：**
    
    **[DETAILED_REPORT_START]**
    (Section 1 と Section 2 の内容)
    **[DETAILED_REPORT_END]**

    **[RAW_LOG_START]**
    (Section 3 の内容)
    **[RAW_LOG_END]**

    **[JSON_START]**
    (Section 4 のJSON)
    **[JSON_END]**

    **[MERMAID_START]**
    (Section 5 のMermaidコードのみ。バッククォート不要)
    **[MERMAID_END]**
    ---

    【入力テキスト】
    {transcript_text}
    """

    max_retries = 10
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model=RESOLVED_MODEL_ID, contents=prompt)
            text = response.text.strip()
            break 
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "quota" in err_str or "overloaded" in err_str:
                wait = 60 * (attempt + 1)
                print(f"⏳ Gemini Busy ({RESOLVED_MODEL_ID}). Waiting {wait}s...", flush=True)
                time.sleep(wait)
            else:
                log_error("Gemini Analysis Failed", e)
                return {"student_name": "AnalysisError", "date": datetime.now().strftime('%Y-%m-%d')}, f"Analysis Error: {e}", transcript_text[:2000], None
    else: return {"student_name": "QuotaError", "date": datetime.now().strftime('%Y-%m-%d')}, "Quota Limit Exceeded", transcript_text[:2000], None

    def extract_safe(s, e, src):
        m = re.search(f'{re.escape(s)}(.*?){re.escape(e)}', src, re.DOTALL)
        return m.group(1).strip() if m else None

    report = extract_safe("[DETAILED_REPORT_START]", "[DETAILED_REPORT_END]", text)
    time_log = extract_safe("[RAW_LOG_START]", "[RAW_LOG_END]", text)
    json_str = extract_safe("[JSON_START]", "[JSON_END]", text)
    mermaid_code = extract_safe("[MERMAID_START]", "[MERMAID_END]", text)

    if not report:
        print("⚠️ Warning: Missing REPORT tags. Fallback...", flush=True)
        if "[RAW_LOG_START]" in text:
            report = text.split("[RAW_LOG_START]")[0].replace("[DETAILED_REPORT_START]", "").strip()
        else:
            report = text

    if not time_log: time_log = "Log tags missing."
    
    if not mermaid_code:
        m_match = re.search(r'```mermaid(.*?)```', text, re.DOTALL)
        if m_match: mermaid_code = m_match.group(1).strip()
    
    if mermaid_code:
        mermaid_code = mermaid_code.replace("**", "").replace("```mermaid", "").replace("```", "").strip()

    try: 
        if json_str: data = json.loads(json_str)
        else: raise ValueError("No JSON block")
    except: 
        try:
            json_candidate = re.search(r'\{.*"student_name".*\}', text, re.DOTALL)
            if json_candidate: data = json.loads(json_candidate.group(0))
            else: data = {"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "Check Logs"}
        except:
            data = {"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "Check Logs"}
            
    return data, report, time_log, mermaid_code
def text_to_notion_blocks(text):
    blocks = []
    lines = text.split('\n')
    
    for line in lines:
        if not line.strip():
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": []} 
            })
            continue
        
        if line.startswith('|') or line.startswith('+-'):
             continue 

        clean_content = line[:1900] 
        
        if line.startswith('### '):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": clean_content[4:]}}]}
            })
        elif line.startswith('## '):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": clean_content[3:]}}]}
            })
        elif line.startswith('# '):
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": clean_content[2:]}}]}
            })
        elif line.startswith('- ') or line.startswith('* '):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": clean_content[2:]}}]}
            })
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": clean_content}}]}
            })
            
    return blocks

# --- 5. Asset Management ---

def notion_create_page_heavy(db_id, props, children):
    print(f"📤 Posting to Notion DB: {db_id}...", flush=True)
    res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json={"parent": {"database_id": db_id}, "properties": props, "children": children[:100]})
    if res.status_code != 200:
        print(f"⚠️ Initial Post Failed ({res.status_code}). Retrying with SAFE MODE...", flush=True)
        safe_props = {}
        for key, val in props.items():
            if "title" in val: safe_props[key] = val; break
        if not safe_props:
             content_text = props.get("名前", {}).get("title", [{}])[0].get("text", {}).get("content", "Log")
             safe_props = {"Name": {"title": [{"text": {"content": content_text}}]}}
        date_val = props.get("日付", {}).get("date", {}).get("start", "Unknown")
        error_note = {"object": "block", "type": "callout", "callout": {"rich_text": [{"text": {"content": f"⚠️ Date Prop Missing. Date: {date_val}"}}]}}
        children.insert(0, error_note)
        res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json={"parent": {"database_id": db_id}, "properties": safe_props, "children": children[:100]})
        if res.status_code != 200:
            print(f"❌ NOTION SAFE MODE FAILED: {res.status_code}\n{res.text}", flush=True)
            return

    response_data = res.json()
    pid = response_data.get('id')
    print(f"🔗 Notion Page Created: {response_data.get('url')}", flush=True)
    if pid and len(children) > 100:
        for i in range(100, len(children), 100):
            requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": children[i:i+100]})

def ensure_processed_folder():
    try:
        q = f"name='processed_coaching_logs' and '{INBOX_FOLDER_ID}' in parents"
        folders = drive_service.files().list(q=q).execute().get('files', [])
        if folders: return folders[0]['id']
        folder = drive_service.files().create(body={'name': 'processed_coaching_logs', 'mimeType': 'application/vnd.google-apps.folder', 'parents': [INBOX_FOLDER_ID]}, fields='id').execute()
        return folder.get('id')
    except Exception as e:
        log_error("Failed to Get/Create Processed Folder", e)
        return INBOX_FOLDER_ID

def upload_file_to_drive(local_path, folder_id, rename_to, mime_type):
    print(f"📤 Uploading {rename_to}...", flush=True)
    try:
        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True, chunksize=100*1024*1024)
        drive_service.files().create(
            body={'name': rename_to, 'parents': [folder_id]}, 
            media_body=media, 
            fields='id',
            supportsAllDrives=True
        ).execute()
        print("✅ Upload Complete.", flush=True)
    except Exception as e:
        log_error(f"Upload Failed for {rename_to}", e)

def move_original_file(file_id, folder_id):
    if folder_id == INBOX_FOLDER_ID:
        print("⚠️ Skipping Move: Destination is Inbox.", flush=True)
        return
    try:
        prev_parents = drive_service.files().get(fileId=file_id, fields='parents').execute().get('parents', [])
        prev_str = ",".join(prev_parents)
        drive_service.files().update(
            fileId=file_id, 
            addParents=folder_id, 
            removeParents=prev_str,
            supportsAllDrives=True
        ).execute()
        print(f"📦 Archived original file to folder [{folder_id}].", flush=True)
    except Exception as e:
        log_error(f"Move Original File Failed (ID: {file_id})", e)
        print(f"👉 TIP: Add this email to folder permissions: {BOT_EMAIL}", flush=True)

# --- Main ---
def main():
    print("--- SZ AUTO LOGGER ULTIMATE (v130.0 - Dynamic Spec Selection) ---", flush=True)
    
    # 接続テスト済みのRESOLVED_MODEL_IDがすでにセットアップされている状態で開始
    if not RESOLVED_MODEL_ID:
        print("❌ Model Selection Failed during Setup. Aborting.")
        return

    load_student_registry()
    
    try:
        files = drive_service.files().list(
            q=f"'{INBOX_FOLDER_ID}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
            fields="files(id, name, createdTime)"
        ).execute().get('files', [])
    except Exception: return

    if not files: print("ℹ️ No files."); return

    for file in files:
        try:
            print(f"\n📂 Processing: {file['name']}")
            safe_name = sanitize_filename(file['name'])
            fpath = os.path.join(TEMP_DIR, safe_name)
            
            # Download
            max_dl_retries = 3
            for dl_attempt in range(max_dl_retries):
                try:
                    with open(fpath, "wb") as f:
                        request = drive_service.files().get_media(fileId=file['id'])
                        downloader = MediaIoBaseDownload(f, request, chunksize=100*1024*1024)
                        done = False
                        while done is False:
                            status, done = downloader.next_chunk()
                            print(f"   ⬇️ Downloading... {int(status.progress() * 100)}%", end="\r", flush=True)
                    print("\n✅ Download Complete.")
                    break 
                except Exception as e:
                    print(f"\n⚠️ Download Interrupted: {e}. Retrying...", flush=True)
                    time.sleep(5)
            else:
                print("❌ Download Failed. Skipping.")
                continue

            srcs = []
            candidate_raw_name = None

            if safe_name.endswith('.zip'):
                try:
                    patoolib.extract_archive(fpath, outdir=TEMP_DIR)
                    extracted_files = []
                    for r, _, fs in os.walk(TEMP_DIR):
                        for af in fs:
                            full_p = os.path.join(r, af)
                            extracted_files.append(full_p)
                            if af.lower().endswith(('.flac', '.mp3', '.m4a', '.wav')) and 'final_mix' not in af and 'chunk' not in af:
                                srcs.append(full_p)
                    candidate_raw_name = detect_student_candidate_raw(extracted_files, file['name'])
                except Exception as e:
                    log_error(f"Archive Extraction Failed", e)
                    continue
            else: srcs.append(fpath)
            
            if not srcs: print("ℹ️ No audio files found."); continue
            
            # Processing
            precise_datetime, date_only = extract_date_smart(file['name'], file.get('createdTime'))
            mixed = mix_audio_ffmpeg(srcs)
            chunks = split_audio_ffmpeg(mixed)
            full_text = transcribe_with_groq(chunks)
            
            # Analysis
            meta, report, logs, mermaid_code = analyze_text_with_gemini(full_text, precise_datetime, candidate_raw_name)
            
            # DB Matching
            did, oname = find_best_student_match(meta['student_name'])
            
            # --- Build Notion Blocks (UPDATED) ---
            final_blocks = []

            # 1. Detailed Report
            report_header = "### 📊 SZメソッド詳細分析\n\n" + report
            final_blocks.extend(text_to_notion_blocks(report_header))

            # 2. Mermaid Block
            if mermaid_code:
                final_blocks.append({"object": "block", "type": "divider", "divider": {}})
                final_blocks.append({
                    "object": "block", 
                    "type": "heading_2", 
                    "heading_2": {"rich_text": [{"text": {"content": "🧠 思考フローチャート"}}]}
                })
                final_blocks.append({
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [{"text": {"content": "上の分析内容を構造化したものです。判断に迷った時の地図として使ってください。"}}],
                        "icon": {"emoji": "🗺️"}
                    }
                })
                final_blocks.append({
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"type": "text", "text": {"content": mermaid_code}}],
                        "language": "mermaid" 
                    }
                })

            # 3. Logs
            logs_content = f"\n---\n\n### 📝 時系列ログ\n\n{logs}"
            final_blocks.extend(text_to_notion_blocks(logs_content))

            # 4. Transcript
            final_blocks.append({"object": "block", "type": "divider", "divider": {}})
            final_blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "📜 全文文字起こし"}}]}})
            
            for i in range(0, len(full_text), 1900):
                chunk_text = full_text[i:i+1900]
                final_blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": chunk_text}}]}})
            
            props = {
                "名前": {"title": [{"text": {"content": f"{precise_datetime} {oname} 通話ログ"}}]}, 
                "日付": {"date": {"start": date_only}}
            }

            print("💾 Saving to Fallback DB (All Data)...")
            notion_create_page_heavy(sanitize_id(FINAL_FALLBACK_DB_ID), copy.deepcopy(props), copy.deepcopy(final_blocks))
            
            if did and did != FINAL_FALLBACK_DB_ID:
                print(f"👤 Saving to Student DB ({oname})...")
                notion_create_page_heavy(sanitize_id(did), copy.deepcopy(props), copy.deepcopy(final_blocks))
            
            # Artifacts
            processed_folder_id = ensure_processed_folder()
            safe_filename_time = precise_datetime.replace(':', '-').replace(' ', '_')
            
            upload_file_to_drive(mixed, processed_folder_id, f"{safe_filename_time}_{oname}_Full.mp3", 'audio/mpeg')
            
            txt_path = os.path.join(TEMP_DIR, "transcript.txt")
            with open(txt_path, "w") as f: f.write(full_text)
            upload_file_to_drive(txt_path, processed_folder_id, f"{safe_filename_time}_{oname}_Transcript.txt", 'text/plain')
            
            move_original_file(file['id'], processed_folder_id)

        except Exception as e:
            log_error(f"Processing Failed for {file['name']}", e)
            continue
        finally:
            if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR); os.makedirs(TEMP_DIR)

if __name__ == "__main__": main()
