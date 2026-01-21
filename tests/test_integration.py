"""
Integration Test: Verify SmashZettel-Bot Structure and Imports

This test validates that:
1. All modules can be imported without errors
2. Key classes and functions are accessible
3. DSPy pipeline is properly configured
4. Configuration files exist

Run: python tests/test_integration.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_directory_structure():
    """Verify required directory structure exists."""
    print("🔍 Testing directory structure...")

    required_dirs = [
        "src",
        "src/brain",
        "src/utils",
        "src/brain/raw_data",
        "data",
    ]

    for dir_path in required_dirs:
        full_path = project_root / dir_path
        assert full_path.exists(), f"Missing directory: {dir_path}"
        print(f"  ✅ {dir_path}")

    print()


def test_imports():
    """Test that all modules can be imported."""
    print("📦 Testing module imports...")

    # Core modules
    try:
        from src.brain.retriever import PineconeRetriever, create_retriever
        print("  ✅ src.brain.retriever")
    except ImportError as e:
        print(f"  ❌ src.brain.retriever: {e}")
        return False

    try:
        from src.brain.model import SmashCoach, AnalysisSignature, AdviceSignature, create_coach
        print("  ✅ src.brain.model")
    except ImportError as e:
        print(f"  ❌ src.brain.model: {e}")
        return False

    try:
        from src.utils import ingest
        print("  ✅ src.utils.ingest")
    except ImportError as e:
        print(f"  ❌ src.utils.ingest: {e}")
        return False

    print()
    return True


def test_configuration_files():
    """Verify configuration files exist."""
    print("⚙️ Testing configuration files...")

    required_files = [
        "requirements.txt",
        ".gitignore",
        ".env.example",
        "Dockerfile",
        "README.md",
    ]

    for file_path in required_files:
        full_path = project_root / file_path
        assert full_path.exists(), f"Missing file: {file_path}"
        print(f"  ✅ {file_path}")

    print()


def test_data_persistence():
    """Verify data directory structure."""
    print("💾 Testing data persistence...")

    data_dir = project_root / "data"
    training_file = data_dir / "training_data.jsonl"

    assert data_dir.exists(), "data/ directory missing"
    print(f"  ✅ data/ directory exists")

    assert training_file.exists(), "data/training_data.jsonl missing"
    print(f"  ✅ data/training_data.jsonl exists")

    print()


def test_dspy_signatures():
    """Verify DSPy Signature definitions."""
    print("🧠 Testing DSPy Signatures...")

    try:
        from src.brain.model import AnalysisSignature, AdviceSignature
        import dspy

        # Check inheritance
        assert issubclass(AnalysisSignature, dspy.Signature)
        print("  ✅ AnalysisSignature is dspy.Signature")

        assert issubclass(AdviceSignature, dspy.Signature)
        print("  ✅ AdviceSignature is dspy.Signature")

    except Exception as e:
        print(f"  ❌ DSPy Signature test failed: {e}")
        return False

    print()
    return True


def test_environment_variables():
    """Check environment variables (warn if missing)."""
    print("🔐 Checking environment variables...")

    required_env = [
        "GEMINI_API_KEY",
        "PINECONE_API_KEY",
        "DISCORD_TOKEN",
    ]

    missing = []
    for var in required_env:
        if os.getenv(var):
            print(f"  ✅ {var} is set")
        else:
            print(f"  ⚠️  {var} not set (required for runtime)")
            missing.append(var)

    print()

    if missing:
        print(f"⚠️  {len(missing)} environment variables missing.")
        print("   See .env.example for setup instructions.")
        return False

    return True


def main():
    """Run all integration tests."""
    print("=" * 60)
    print("SmashZettel-Bot Integration Test Suite")
    print("=" * 60)
    print()

    try:
        test_directory_structure()
        test_configuration_files()
        test_data_persistence()

        if not test_imports():
            print("❌ Import test failed")
            return False

        if not test_dspy_signatures():
            print("❌ DSPy signature test failed")
            return False

        env_ok = test_environment_variables()

        print("=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)

        if not env_ok:
            print("\n⚠️  Note: Set required environment variables before running bot.")
            print("   See .env.example for configuration template.")

        return True

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
