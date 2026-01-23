#!/usr/bin/env python3
"""
Integration Test Suite: Validates DSPy Architecture
Tests:
1. Notion → Pinecone pipeline
2. raw_data completeness analysis
3. DSPy Module composition
4. Discord bot command routing
5. Training data persistence (JSONL)
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

def test_dspy_modules():
    """Test 1: DSPy Module composition"""
    print("\n" + "="*70)
    print("TEST 1: DSPy Module Composition")
    print("="*70)
    
    try:
        from src.brain.retriever import PineconeRetriever, create_retriever
        from src.brain.model import SmashCoach, AnalysisSignature, AdviceSignature, create_coach
        import dspy
        
        # Check inheritance
        assert issubclass(PineconeRetriever, dspy.Retrieve), "❌ PineconeRetriever must inherit dspy.Retrieve"
        assert issubclass(SmashCoach, dspy.Module), "❌ SmashCoach must inherit dspy.Module"
        print("✅ PineconeRetriever inherits dspy.Retrieve")
        print("✅ SmashCoach inherits dspy.Module")
        
        # Check Signatures
        assert issubclass(AnalysisSignature, dspy.Signature), "❌ AnalysisSignature must inherit dspy.Signature"
        assert issubclass(AdviceSignature, dspy.Signature), "❌ AdviceSignature must inherit dspy.Signature"
        print("✅ AnalysisSignature inherits dspy.Signature")
        print("✅ AdviceSignature inherits dspy.Signature")
        
        # Check docstrings with DSPy markers
        assert "===" in PineconeRetriever.__doc__, "❌ PineconeRetriever docstring missing DSPy markers (===)"
        assert "===" in SmashCoach.__doc__, "❌ SmashCoach docstring missing DSPy markers (===)"
        assert "===" in SmashCoach.forward.__doc__, "❌ SmashCoach.forward() docstring missing DSPy markers (===)"
        print("✅ All Module docstrings contain DSPy section markers (===)")
        
        return True
    except Exception as e:
        print(f"❌ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_notion_sync_structure():
    """Test 2: Notion sync module exists and is callable"""
    print("\n" + "="*70)
    print("TEST 2: Notion Sync Pipeline Structure")
    print("="*70)
    
    try:
        from src.utils.notion_sync import (
            sync_notion_to_pinecone,
            fetch_theory_pages,
            embed_and_upsert
        )
        
        # Check function signatures
        import inspect
        sig = inspect.signature(sync_notion_to_pinecone)
        assert 'verbose' in sig.parameters, "❌ sync_notion_to_pinecone missing 'verbose' parameter"
        print("✅ sync_notion_to_pinecone has correct signature")
        
        # Check return type annotation
        assert sig.return_annotation != inspect.Parameter.empty, "❌ sync_notion_to_pinecone missing return type"
        print("✅ sync_notion_to_pinecone has return type annotation")
        
        print("✅ Notion sync module structure validated")
        return True
    except Exception as e:
        print(f"❌ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_raw_data_analysis_structure():
    """Test 3: Raw data analysis module exists"""
    print("\n" + "="*70)
    print("TEST 3: Raw Data Analysis Structure")
    print("="*70)
    
    try:
        from src.utils.analyze_raw_data import (
            analyze_raw_data,
            estimate_completeness,
            identify_gaps,
            generate_enhancement_report
        )
        
        # Check raw_data directory exists
        raw_data_dir = Path('/workspaces/auto-coaching-log/src/brain/raw_data')
        assert raw_data_dir.exists(), f"❌ raw_data directory not found at {raw_data_dir}"
        txt_files = list(raw_data_dir.glob('*.txt'))
        assert len(txt_files) > 0, f"❌ No .txt files found in {raw_data_dir}"
        print(f"✅ Found {len(txt_files)} raw_data/*.txt files")
        
        # Test completeness estimator
        test_content = """
        # Test Document
        
        Formula: $\frac{knockback}{weight} = \text{speed}$
        
        - List item 1
        - List item 2
        - List item 3
        
        | Header 1 | Header 2 |
        |----------|----------|
        | Data 1   | Data 2   |
        """
        
        score = estimate_completeness(test_content)
        assert 0.0 <= score <= 1.0, f"❌ Completeness score out of range: {score}"
        assert score > 0.5, f"❌ Completeness score too low for test content: {score}"
        print(f"✅ Completeness estimator working (test score: {score:.2f})")
        
        print("✅ Raw data analysis module structure validated")
        return True
    except Exception as e:
        print(f"❌ TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_data_persistence():
    """Test 4: Training data persistence"""
    print("\n" + "="*70)
    print("TEST 4: Training Data Persistence (JSONL)")
    print("="*70)
    
    try:
        data_dir = Path('/workspaces/auto-coaching-log/data')
        data_dir.mkdir(exist_ok=True)
        
        jsonl_path = data_dir / 'training_data.jsonl'
        
        # Create test entry
        test_entry = {
            'question': 'テスト質問ですか？',
            'gold_answer': 'これはテスト回答です。',
            'user_correction': 'より良い回答はこれです。',
            'timestamp': datetime.now().isoformat()
        }
        
        # Append to JSONL
        with open(jsonl_path, 'a') as f:
            f.write(json.dumps(test_entry, ensure_ascii=False) + '\n')
        
        # Read back
        entries = []
        with open(jsonl_path, 'r') as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
        
        assert len(entries) > 0, "❌ Failed to read JSONL entries"
        print(f"✅ JSONL persistence working ({len(entries)} entries)")
        
        # Clean up test entry
        with open(jsonl_path, 'w') as f:
            for entry in entries[:-1]:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        
        return True
    except Exception as e:
        print(f"❌ TEST 4 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_discord_bot_structure():
    """Test 5: Discord bot module structure"""
    print("\n" + "="*70)
    print("TEST 5: Discord Bot Structure")
    print("="*70)
    
    try:
        from src.main import _run_coaching, _append_training_data, _commit_to_github
        import inspect
        
        # Check async/sync bridge
        sig = inspect.signature(_run_coaching)
        assert 'query' in sig.parameters, "❌ _run_coaching missing 'query' parameter"
        print("✅ _run_coaching has correct signature")
        
        # Check docstring explains async/sync bridge
        assert _run_coaching.__doc__ is not None, "❌ _run_coaching missing docstring"
        assert "asyncio.to_thread" in _run_coaching.__doc__ or "Thread" in _run_coaching.__doc__, \
            "❌ _run_coaching docstring doesn't explain async/sync bridge"
        print("✅ _run_coaching docstring explains async/sync bridge")
        
        # Check training data function
        sig = inspect.signature(_append_training_data)
        assert 'entry' in sig.parameters, "❌ _append_training_data missing 'entry' parameter"
        print("✅ _append_training_data has correct signature")
        
        return True
    except Exception as e:
        print(f"❌ TEST 5 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_environment_configuration():
    """Test 6: Environment configuration"""
    print("\n" + "="*70)
    print("TEST 6: Environment Configuration")
    print("="*70)
    
    try:
        required_keys = [
            'GEMINI_API_KEY',
            'PINECONE_API_KEY',
            'DISCORD_BOT_TOKEN'
        ]
        
        missing_keys = []
        for key in required_keys:
            if not os.getenv(key):
                missing_keys.append(key)
        
        if missing_keys:
            print(f"⚠️  Missing environment variables: {', '.join(missing_keys)}")
            print("   (This is OK for testing - will fail when actually calling APIs)")
        else:
            print("✅ All required environment variables set")
        
        # Check .env.example exists
        env_example = Path('/workspaces/auto-coaching-log/.env.example')
        assert env_example.exists(), "❌ .env.example not found"
        print("✅ .env.example exists")
        
        return True
    except Exception as e:
        print(f"❌ TEST 6 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_documentation():
    """Test 7: Documentation completeness"""
    print("\n" + "="*70)
    print("TEST 7: Documentation")
    print("="*70)
    
    try:
        docs = {
            'DSPY_DESIGN.md': 'DSPy architecture documentation',
            'IMPLEMENTATION_SUMMARY.md': 'Implementation overview',
            'README.md': 'Project README'
        }
        
        for doc, desc in docs.items():
            path = Path(f'/workspaces/auto-coaching-log/{doc}')
            assert path.exists(), f"❌ {doc} not found"
            content = path.read_text()
            assert len(content) > 100, f"❌ {doc} appears empty"
            print(f"✅ {doc} ({len(content)} bytes)")
        
        return True
    except Exception as e:
        print(f"❌ TEST 7 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("\n" + "="*70)
    print("🧪 SmashZettel-Bot: Comprehensive Integration Test Suite")
    print("="*70)
    
    tests = [
        ("DSPy Module Composition", test_dspy_modules),
        ("Notion Sync Pipeline", test_notion_sync_structure),
        ("Raw Data Analysis", test_raw_data_analysis_structure),
        ("Data Persistence", test_data_persistence),
        ("Discord Bot Structure", test_discord_bot_structure),
        ("Environment Config", test_environment_configuration),
        ("Documentation", test_documentation)
    ]
    
    results = []
    for test_name, test_func in tests:
        results.append(test_func())
    
    print("\n" + "="*70)
    print("📊 Test Summary")
    print("="*70)
    
    passed = sum(results)
    total = len(results)
    
    print(f"Passed: {passed}/{total}")
    
    for (test_name, _), result in zip(tests, results):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {test_name}")
    
    if passed == total:
        print("\n🎉 All tests PASSED!")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) FAILED")
        return 1

if __name__ == '__main__':
    sys.exit(main())
