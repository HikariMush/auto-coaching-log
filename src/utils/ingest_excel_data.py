#!/usr/bin/env python3
"""
SmashZettel-Bot: Technique Data Ingestion from Excel + Text Data
Combines Excel frame data with raw_data text files for comprehensive technique knowledge base.

Usage:
    python -m src.utils.ingest_excel_data [--resume] [--dry-run]
"""

import os
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import re

import openpyxl
import google.generativeai as genai
from pinecone import Pinecone

# Configuration
EXCEL_FILE = Path(__file__).parent.parent / 'brain' / 'raw_data' / 'スマブラSP フレームデータ by検証窓.xlsx'
RAW_DATA_DIR = Path(__file__).parent.parent / 'brain' / 'raw_data'
DATA_DIR = Path(__file__).parent.parent.parent / 'data'
INGESTION_STATE_FILE = DATA_DIR / 'excel_ingestion_state.json'


def initialize_apis() -> Tuple[Any, Pinecone]:
    """Initialize Google Generative AI and Pinecone"""
    
    # Initialize Gemini
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    genai.configure(api_key=api_key)
    
    # Initialize Pinecone
    pinecone_key = os.environ.get('PINECONE_API_KEY')
    if not pinecone_key:
        raise ValueError("PINECONE_API_KEY environment variable not set")
    
    pc = Pinecone(api_key=pinecone_key)
    return genai, pc


def load_excel_workbook() -> openpyxl.Workbook:
    """Load Excel workbook"""
    if not EXCEL_FILE.exists():
        raise FileNotFoundError(f"Excel file not found: {EXCEL_FILE}")
    
    print(f"📂 Loading Excel file: {EXCEL_FILE.name}")
    wb = openpyxl.load_workbook(EXCEL_FILE, data_only=False)
    print(f"✅ Found {len(wb.sheetnames)} character sheets\n")
    
    return wb


def extract_excel_sections(sheet: openpyxl.worksheet.worksheet.Worksheet, 
                          character_name: str) -> Dict[str, List[str]]:
    """
    Extract structured sections from Excel sheet
    
    Returns:
        {
            '行動フレーム': ['Jab data...', 'Up-tilt data...', ...],
            '能力値': ['Weight: 98', 'Fall speed: 1.6', ...],
            '滞空フレーム': ['Jump: 45', 'Air time: 12', ...],
        }
    """
    
    sections = {
        '行動フレーム': [],
        '能力値': [],
        '滞空フレーム': [],
    }
    
    # Map headers to section names
    section_keywords = {
        '行動フレーム': '行動フレーム',
        '能力値': '能力値',
        '滞空フレーム': '滞空フレーム',
    }
    
    current_section = None
    current_buffer = []
    
    # Scan all rows
    for row_idx in range(1, sheet.max_row + 1):
        row_data = []
        
        for col_idx in range(1, min(sheet.max_column + 1, 15)):  # First 15 columns
            cell = sheet.cell(row_idx, col_idx)
            if cell.value is None:
                continue
            
            value = str(cell.value)
            
            # Skip formulas and images
            if value.startswith("='") or value.startswith('=') or '<' in value:
                continue
            
            row_data.append(value.strip())
        
        if not row_data:
            continue
        
        row_text = ' | '.join(row_data)
        
        # Check for section header
        for section_key, header in section_keywords.items():
            if header in row_text:
                # Save previous buffer
                if current_buffer and current_section:
                    sections[current_section].append(' | '.join(current_buffer))
                
                current_section = section_key
                current_buffer = []
                break
        else:
            # Add to current buffer
            if current_section and len(row_data) >= 2:
                current_buffer.extend(row_data)
                
                # If buffer is getting long, flush it
                if len(current_buffer) > 20:
                    sections[current_section].append(' | '.join(current_buffer))
                    current_buffer = []
    
    # Flush remaining buffer
    if current_buffer and current_section:
        sections[current_section].append(' | '.join(current_buffer))
    
    # Clean up sections
    for section in sections:
        # Remove duplicates and empty strings
        sections[section] = [s.strip() for s in sections[section] if s.strip()]
    
    return sections


def load_raw_text_data() -> Dict[str, str]:
    """Load raw text data from .txt files"""
    
    text_data = {}
    
    if not RAW_DATA_DIR.exists():
        return text_data
    
    for txt_file in RAW_DATA_DIR.glob('*.txt'):
        section_name = txt_file.stem  # Filename without .txt
        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                content = f.read()
                text_data[section_name] = content
        except Exception as e:
            print(f"⚠️  Could not read {txt_file}: {e}")
    
    return text_data


def format_technique_text(character: str, section: str, data: str) -> str:
    """Format technique data as structured text for embedding"""
    
    lines = [
        f"【キャラクター】{character}",
        f"【カテゴリ】{section}",
        f"【データ】{data[:500]}",  # Limit to 500 chars
    ]
    
    return "\n".join(lines)


def embed_text(genai_client: Any, text: str) -> Optional[List[float]]:
    """Generate embedding for text using Gemini embedding-001"""
    
    try:
        response = genai_client.embed_content(
            model="models/embedding-001",
            content=text,
            task_type="SEMANTIC_SIMILARITY"
        )
        return response['embedding']
    except Exception as e:
        print(f"⚠️  Embedding failed: {e}")
        return None


def save_to_pinecone(pc: Pinecone, character: str, section: str, data: str,
                     embedding: List[float], batch_id: int) -> bool:
    """Save technique data to Pinecone"""
    
    try:
        # Get or create index
        index_name = "smash-coaching"
        try:
            index = pc.Index(index_name)
        except:
            print(f"📌 Creating Pinecone index: {index_name}")
            pc.create_index(
                name=index_name,
                dimension=768,
                metric="cosine"
            )
            index = pc.Index(index_name)
        
        # Create unique ID
        char_clean = character.replace(' ', '_').replace('・', '-')
        section_clean = section.replace(' ', '_')
        vector_id = f"excel_{char_clean}_{section_clean}_{batch_id}"
        
        # Prepare metadata
        metadata = {
            'character': character,
            'section': section,
            'source': 'excel_ingestion',
            'ingested_at': datetime.now().isoformat(),
            'data_preview': data[:200],
        }
        
        # Upsert to Pinecone
        index.upsert(vectors=[
            (vector_id, embedding, metadata)
        ])
        
        return True
    
    except Exception as e:
        print(f"⚠️  Failed to save to Pinecone: {e}")
        return False


def get_ingestion_state() -> Dict[str, Any]:
    """Load ingestion state"""
    if INGESTION_STATE_FILE.exists():
        with open(INGESTION_STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    return {
        'ingested_sheets': [],
        'ingested_entries': 0,
        'failed_entries': 0,
        'start_time': datetime.now().isoformat(),
        'last_update': None
    }


def save_ingestion_state(state: Dict[str, Any]) -> None:
    """Save ingestion state"""
    state['last_update'] = datetime.now().isoformat()
    
    DATA_DIR.mkdir(exist_ok=True)
    with open(INGESTION_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def ingest_excel_data(genai_client: Any, pc: Pinecone, dry_run: bool = False,
                     resume: bool = False) -> None:
    """Main ingestion workflow"""
    
    print("\n" + "="*70)
    print("📊 Excel + Text Data Ingestion")
    print("="*70 + "\n")
    
    # Load workbook
    wb = load_excel_workbook()
    
    # Load raw text data
    print("📚 Loading raw text data...")
    text_data = load_raw_text_data()
    print(f"✅ Found {len(text_data)} text files\n")
    
    # Load ingestion state
    state = get_ingestion_state()
    
    # Process each character sheet
    ingested_count = 0
    failed_count = 0
    
    for sheet_idx, sheet_name in enumerate(wb.sheetnames[1:], start=1):
        
        # Skip if already ingested and not resuming
        if sheet_name in state['ingested_sheets'] and not resume:
            continue
        
        # Extract character name
        match = re.search(r'[0-9０-９]+\.\s*(.+)', sheet_name)
        character_name = match.group(1) if match else sheet_name
        
        print(f"[{sheet_idx}/{len(wb.sheetnames)-1}] Processing: {character_name}")
        
        try:
            # Extract sections from Excel
            sheet = wb[sheet_name]
            sections = extract_excel_sections(sheet, character_name)
            
            # Process each section
            entry_idx = 0
            for section_name, entries in sections.items():
                if not entries:
                    continue
                
                print(f"  📍 {section_name}: {len(entries)} entries")
                
                for entry in entries:
                    if not entry or len(entry) < 5:
                        continue
                    
                    try:
                        # Format text
                        text = format_technique_text(character_name, section_name, entry)
                        
                        if dry_run:
                            print(f"    [DRY-RUN] Would embed: {text[:80]}...")
                            ingested_count += 1
                        else:
                            # Generate embedding
                            embedding = embed_text(genai_client, text)
                            
                            if not embedding:
                                failed_count += 1
                                continue
                            
                            # Save to Pinecone
                            success = save_to_pinecone(pc, character_name, section_name,
                                                     entry, embedding, entry_idx)
                            
                            if success:
                                ingested_count += 1
                            else:
                                failed_count += 1
                    
                    except Exception as e:
                        print(f"    ⚠️  Entry {entry_idx} failed: {e}")
                        failed_count += 1
                    
                    entry_idx += 1
            
            # Mark sheet as ingested
            state['ingested_sheets'].append(sheet_name)
            state['ingested_entries'] += ingested_count
            
            print(f"  ✅ Complete\n")
        
        except Exception as e:
            print(f"  ❌ Failed: {e}\n")
            failed_count += 1
    
    # Save final state
    if not dry_run:
        save_ingestion_state(state)
    
    # Summary
    print("="*70)
    print("📊 Ingestion Summary")
    print("="*70)
    print(f"✅ Ingested: {ingested_count} entries")
    print(f"❌ Failed: {failed_count} entries")
    print(f"📋 Sheets processed: {len(state['ingested_sheets'])}")
    if not dry_run:
        print(f"💾 State saved to: {INGESTION_STATE_FILE}")
    print()


def main():
    """Main entry point"""
    
    dry_run = '--dry-run' in sys.argv
    resume = '--resume' in sys.argv
    
    try:
        # Check if file exists
        if not EXCEL_FILE.exists():
            print(f"❌ Excel file not found: {EXCEL_FILE}")
            sys.exit(1)
        
        # Initialize APIs (skip in dry-run)
        if not dry_run:
            print("🔌 Initializing APIs...")
            genai_client, pc = initialize_apis()
            print("✅ APIs initialized\n")
        else:
            genai_client, pc = None, None
        
        # Run ingestion
        ingest_excel_data(genai_client, pc, dry_run=dry_run, resume=resume)
        
        print("🎉 Done!")
    
    except KeyboardInterrupt:
        print("\n⏸️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
