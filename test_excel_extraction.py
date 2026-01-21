#!/usr/bin/env python3
"""
Test script for Excel data extraction
"""

import sys
from pathlib import Path

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.ingest_excel_data import (
    load_excel_workbook,
    extract_character_data,
    format_technique_text,
)

def test_excel_extraction():
    """Test excel extraction without API calls"""
    
    print("\n" + "="*70)
    print("🧪 Excel Data Extraction Test")
    print("="*70 + "\n")
    
    # Load workbook
    print("📂 Loading Excel file...")
    wb = load_excel_workbook()
    
    # Test extraction on first 3 characters
    test_sheets = [s for s in wb.sheetnames if s != 'トップページ'][:3]
    
    for sheet_name in test_sheets:
        print(f"\n{'─'*70}")
        print(f"📋 Sheet: {sheet_name}")
        print(f"{'─'*70}")
        
        sheet = wb[sheet_name]
        char_data = extract_character_data(sheet, sheet_name)
        
        print(f"✅ Character: {char_data['character']}")
        print(f"   Total rows: {len(char_data['all_rows'])}")
        
        # Show sections
        for section_name, section_entries in char_data['sections'].items():
            if section_entries:
                print(f"\n   📍 Section: {section_name} ({len(section_entries)} entries)")
                for i, entry in enumerate(section_entries[:2], 1):
                    text = format_technique_text(char_data['character'], {
                        'section': section_name,
                        'data': entry.get('data', []),
                        'text': entry.get('text', ''),
                    })
                    print(f"\n      Entry {i}:")
                    for line in text.split('\n'):
                        print(f"      {line}")
    
    print(f"\n{'='*70}")
    print("✅ Test Complete")
    print("="*70)

if __name__ == '__main__':
    try:
        test_excel_extraction()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
