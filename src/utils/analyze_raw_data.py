"""
Raw Data Quality Analysis & Enhancement

Analyzes src/brain/raw_data/*.txt files for coverage and gaps.
Provides recommendations for improving completeness.

DSPy Context:
- Data quality audit tool (not part of reasoning pipeline).
- Identifies gaps for knowledge base enhancement.
- Prepares metadata for improved retrieval.
"""

import os
import glob
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any, Set


def analyze_raw_data() -> Dict[str, Any]:
    """
    Analyze raw_data/*.txt files for structure and coverage.

    Returns:
    --------
    Dict[str, Any]
        Analysis report with coverage statistics and gaps.
    """
    data_dir = Path("src/brain/raw_data")
    txt_files = sorted(glob.glob(str(data_dir / "*.txt")))

    analysis = {
        "total_files": len(txt_files),
        "total_size_mb": sum(os.path.getsize(f) for f in txt_files) / (1024 * 1024),
        "files": [],
        "categories": defaultdict(list),
        "coverage": {},
        "identified_gaps": [],
    }

    # Expected categories for complete SmashBros knowledge
    expected_categories = {
        "攻撃系": ["攻撃判定", "硬直差", "判定", "相殺", "ヒットストップ"],
        "防御系": ["シールド", "ガード硬直", "ジャストシールド"],
        "移動系": ["ダッシュ", "ジャンプ", "着地", "ガケ", "受け身"],
        "ふっとび系": ["ふっとばし力", "ふっとび", "ベクトル変更"],
        "その他": ["アーマー", "アクション", "先行入力"],
    }

    # Analyze each file
    for file_path in txt_files:
        filename = os.path.basename(file_path)
        category = filename.replace(".txt", "")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            file_info = {
                "filename": filename,
                "size_kb": os.path.getsize(file_path) / 1024,
                "lines": len(content.split("\n")),
                "has_formulas": bool(re.search(r"\$.*\$", content)),
                "has_lists": bool(re.search(r"^[\s]*[-*]", content, re.MULTILINE)),
                "has_tables": bool(re.search(r"\|.*\|", content)),
                "completeness_estimate": estimate_completeness(content),
            }

            analysis["files"].append(file_info)

            # Categorize
            for cat_key, keywords in expected_categories.items():
                if any(kw in category for kw in keywords):
                    analysis["categories"][cat_key].append(filename)
                    break
            else:
                analysis["categories"]["Unclassified"].append(filename)

        except Exception as e:
            print(f"⚠️  Error reading {filename}: {e}")

    # Calculate coverage
    coverage_summary = {}
    for cat, files in analysis["categories"].items():
        coverage_summary[cat] = {
            "count": len(files),
            "files": files,
        }
    analysis["coverage"] = coverage_summary

    # Identify gaps
    analysis["identified_gaps"] = identify_gaps(analysis["files"])

    return analysis


def estimate_completeness(content: str) -> float:
    """
    Heuristic estimation of data completeness (0.0-1.0).

    Criteria:
    - Has mathematical formulas: +0.3
    - Has structured lists: +0.2
    - Has tables: +0.2
    - Length > 5KB: +0.15
    - Has cross-references: +0.15
    """
    score = 0.0

    if re.search(r"\$.*\$", content):
        score += 0.3
    if re.search(r"^[\s]*[-*]", content, re.MULTILINE):
        score += 0.2
    if re.search(r"\|.*\|", content):
        score += 0.2
    if len(content) > 5000:
        score += 0.15
    if re.search(r"(\[|【).*(\]|】)", content):  # Cross-references
        score += 0.15

    return min(score, 1.0)


def identify_gaps(files: List[Dict]) -> List[str]:
    """
    Identify files with low completeness that may need enhancement.

    Parameters:
    -----------
    files : List[Dict]
        List of file analysis dictionaries.

    Returns:
    --------
    List[str]
        Filenames with suggested improvements.
    """
    gaps = []

    for file_info in files:
        completeness = file_info["completeness_estimate"]

        # Flag as gap if low completeness AND small size
        if completeness < 0.3 and file_info["size_kb"] < 10:
            gaps.append(
                f"{file_info['filename']} (completeness: {completeness:.1%}, size: {file_info['size_kb']:.1f}KB)"
            )
        elif file_info["lines"] < 20 and completeness < 0.2:
            gaps.append(
                f"{file_info['filename']} (too short: {file_info['lines']} lines)"
            )

    return gaps


def generate_enhancement_report():
    """
    Generate comprehensive analysis and enhancement recommendations.
    """
    print("=" * 70)
    print("📊 SmashBros Knowledge Base: Raw Data Analysis")
    print("=" * 70)

    analysis = analyze_raw_data()

    print(f"\n📈 Statistics:")
    print(f"   Total Files: {analysis['total_files']}")
    print(f"   Total Size: {analysis['total_size_mb']:.1f} MB")

    print(f"\n📁 Category Breakdown:")
    for cat, data in analysis["coverage"].items():
        print(f"   {cat}: {data['count']} files")
        for filename in data["files"][:3]:  # Show first 3
            print(f"      - {filename}")
        if len(data["files"]) > 3:
            print(f"      ... and {len(data['files']) - 3} more")

    print(f"\n🔍 File Quality Analysis:")
    print(f"   {'File':<35} {'Size':<10} {'Completeness':<15}")
    print(f"   {'-' * 60}")
    for file_info in sorted(analysis["files"], key=lambda x: x["completeness_estimate"]):
        completeness_pct = file_info["completeness_estimate"] * 100
        bar = "█" * int(completeness_pct / 10) + "░" * (10 - int(completeness_pct / 10))
        print(
            f"   {file_info['filename']:<35} {file_info['size_kb']:<10.1f}KB {bar} {completeness_pct:>5.1f}%"
        )

    if analysis["identified_gaps"]:
        print(f"\n⚠️  Improvement Opportunities ({len(analysis['identified_gaps'])}):")
        for gap in analysis["identified_gaps"]:
            print(f"   • {gap}")
    else:
        print(f"\n✅ No significant gaps identified.")

    print(f"\n📋 Recommendations:")
    print(f"   1. Add mathematical formulas to files with < 30% completeness")
    print(f"   2. Include reference tables (frame data, hitbox info, etc.)")
    print(f"   3. Add cross-references between related mechanics")
    print(f"   4. Include character-specific variations where applicable")

    print("\n" + "=" * 70)

    return analysis


if __name__ == "__main__":
    report = generate_enhancement_report()

    # Optionally save to JSON for further analysis
    with open("data/raw_data_analysis.json", "w", encoding="utf-8") as f:
        # Convert defaultdicts to regular dicts for JSON serialization
        report["categories"] = {k: v for k, v in report["categories"].items()}
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("\n💾 Detailed analysis saved to: data/raw_data_analysis.json")
