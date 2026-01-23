#!/bin/bash
# Excel取り込み進捗をリアルタイム表示

echo "📊 Excel取り込み進捗リアルタイム表示"
echo "="*60
echo "Ctrl+C で終了"
echo ""

# 方法を選択
if [ "$1" == "log" ]; then
    # 方法1: ログファイルをリアルタイム監視
    echo "📋 実行ログをリアルタイム表示中..."
    tail -f excel_ingestion_log_v2.txt
    
elif [ "$1" == "state" ]; then
    # 方法2: 状態ファイルを定期的に表示
    echo "📊 状態ファイルを5秒ごとに更新..."
    watch -n 5 "cat data/excel_ingestion_state.json | python -m json.tool"
    
else
    # デフォルト: 両方を表示
    echo "📊 進捗サマリーを5秒ごとに更新..."
    echo ""
    
    while true; do
        clear
        echo "="*60
        echo "📊 Excel取り込み進捗（$(date '+%H:%M:%S')）"
        echo "="*60
        echo ""
        
        # 状態ファイル表示
        if [ -f data/excel_ingestion_state.json ]; then
            python3 -c "
import json
with open('data/excel_ingestion_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)
    
sheets = len(state.get('ingested_sheets', []))
entries = state.get('ingested_entries', 0)
failed = state.get('failed_entries', 0)
last_sheet = state.get('ingested_sheets', ['なし'])[-1] if state.get('ingested_sheets') else 'なし'

print(f'✅ 処理済みシート: {sheets}/101')
print(f'📊 取り込みエントリ: {entries:,}')
print(f'❌ 失敗エントリ: {failed}')
print(f'📍 最後のシート: {last_sheet}')
print(f'')
print(f'進捗率: {sheets/101*100:.1f}%')
print(f'推定残り時間: {(101-sheets)*1.5:.0f}分')
"
        fi
        
        echo ""
        echo "─"*60
        echo "最新ログ（最後の10行）:"
        echo "─"*60
        tail -10 excel_ingestion_log_v2.txt 2>/dev/null || echo "ログファイルなし"
        
        echo ""
        echo "="*60
        echo "次回更新: 5秒後 | Ctrl+C で終了"
        echo "="*60
        
        sleep 5
    done
fi
