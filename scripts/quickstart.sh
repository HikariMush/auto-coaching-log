#!/bin/bash
# SmashZettel-Bot: Quick Start Script
# This script sets up and launches the bot in one command

set -e  # Exit on error

echo "╔════════════════════════════════════════════════════════╗"
echo "║   SmashZettel-Bot: Quick Start Setup & Launch          ║"
echo "╚════════════════════════════════════════════════════════╝"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

function print_step() {
    echo -e "\n${BLUE}[STEP]${NC} $1"
}

function print_success() {
    echo -e "${GREEN}✅${NC} $1"
}

function print_error() {
    echo -e "${RED}❌${NC} $1"
}

function print_warning() {
    echo -e "${YELLOW}⚠️${NC} $1"
}

# STEP 1: Check Python
print_step "Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 not found. Please install Python 3.9+"
    exit 1
fi
PYTHON_VERSION=$(python3 --version | awk '{print $2}')
print_success "Python $PYTHON_VERSION found"

# STEP 2: Check .env file
print_step "Checking environment configuration..."
if [ ! -f ".env" ]; then
    if [ ! -f ".env.example" ]; then
        print_error ".env and .env.example not found"
        exit 1
    fi
    print_warning ".env not found, creating from .env.example..."
    cp .env.example .env
    print_warning "⚠️  Please edit .env with your API keys:"
    echo "   GEMINI_API_KEY=<your-key>"
    echo "   PINECONE_API_KEY=<your-key>"
    echo "   DISCORD_BOT_TOKEN=<your-token>"
    echo ""
    read -p "Have you updated .env? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_error "Please update .env and run again"
        exit 1
    fi
else
    print_success ".env file found"
fi

# STEP 3: Install dependencies
print_step "Installing dependencies..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_success "Virtual environment created"
fi

source venv/bin/activate
pip install --upgrade pip > /dev/null 2>&1
pip install -q -r requirements.txt
print_success "Dependencies installed"

# STEP 4: Validate setup
print_step "Validating setup..."
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()

required = ['GEMINI_API_KEY', 'PINECONE_API_KEY', 'DISCORD_BOT_TOKEN']
missing = []
for key in required:
    if not os.getenv(key):
        missing.append(key)

if missing:
    print(f'❌ Missing: {', '.join(missing)}')
    exit(1)
else:
    print('✅ All required API keys configured')
" || exit 1

# STEP 5: Run tests
print_step "Running tests..."
if python3 test_integration_comprehensive.py > /tmp/test_output.log 2>&1; then
    TEST_RESULTS=$(grep "All tests PASSED" /tmp/test_output.log)
    if [ -n "$TEST_RESULTS" ]; then
        print_success "All integration tests passed"
    fi
else
    print_warning "Some tests may have failed, but continuing..."
fi

# STEP 6: Check data directory
print_step "Setting up data directory..."
mkdir -p data
print_success "Data directory ready"

# STEP 7: Show next steps
print_step "Configuration complete! Choose your next action:"
echo ""
echo "  1. Ingest raw_data to Pinecone (ONE TIME setup):"
echo "     python -m src.utils.ingest"
echo ""
echo "  2. Sync Notion Theory DB (optional, or do this later):"
echo "     python -m src.utils.notion_sync"
echo ""
echo "  3. Run Discord bot:"
echo "     python src/main.py"
echo ""
echo "  4. Check data quality:"
echo "     python -m src.utils.analyze_raw_data"
echo ""
echo "  5. Run optimization (after collecting 30+ /teach corrections):"
echo "     python -m src.utils.optimize_coach"
echo ""
echo "────────────────────────────────────────────────────────"
echo "📖 Documentation:"
echo "   - Setup guide: README.md"
echo "   - Architecture: DSPY_DESIGN.md"
echo "   - Quick commands: PROJECT_GUIDE.md"
echo "   - Optimization flow: OPTIMIZATION_FLOW_GUIDE.md"
echo "────────────────────────────────────────────────────────"
echo ""

# STEP 8: Ask what to do
read -p "Start ingest (1), Sync Notion (2), Launch bot (3), or Analyze data (4)? [3]: " -n 1 -r
echo
case $REPLY in
    1)
        print_step "Running ingest..."
        python -m src.utils.ingest
        ;;
    2)
        print_step "Syncing Notion..."
        python -m src.utils.notion_sync
        ;;
    4)
        print_step "Analyzing raw_data..."
        python -m src.utils.analyze_raw_data
        ;;
    *)
        print_step "Launching Discord bot..."
        echo ""
        echo "🤖 Bot is starting..."
        echo "   Commands:"
        echo "   - /ask <query>    → Get coaching advice"
        echo "   - /teach <query> <correction> → Provide correction"
        echo ""
        python src/main.py
        ;;
esac

deactivate
