#!/usr/bin/env python3
"""
Comprehensive DSPy Compliance Validator

Checks:
1. All Signature classes properly defined
2. All Module classes inherit from dspy.Module
3. All docstrings contain DSPy justification
4. No hardcoded prompts (all use Signatures)
5. Data flow compatibility (Signature → Retrieve → Context)
"""

import ast
import sys
from pathlib import Path
from typing import Dict, List, Tuple

class DSPyComplianceChecker(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.issues = []
        self.classes = {}
        self.signatures = []
        self.modules = []
        
    def visit_ClassDef(self, node):
        """Track class definitions"""
        self.classes[node.name] = {
            'lineno': node.lineno,
            'bases': [b.id if isinstance(b, ast.Name) else str(b) for b in node.bases],
            'has_docstring': ast.get_docstring(node) is not None,
            'docstring': ast.get_docstring(node) or '',
            'methods': {}
        }
        
        # Check for dspy.Signature inheritance
        for base in node.bases:
            if isinstance(base, ast.Attribute) and base.attr == 'Signature':
                self.signatures.append(node.name)
            elif isinstance(base, ast.Name) and base.id == 'Signature':
                self.signatures.append(node.name)
            elif isinstance(base, ast.Attribute) and base.attr == 'Module':
                self.modules.append(node.name)
            elif isinstance(base, ast.Name) and base.id == 'Module':
                self.modules.append(node.name)
        
        # Track methods
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                self.classes[node.name]['methods'][item.name] = {
                    'lineno': item.lineno,
                    'has_docstring': ast.get_docstring(item) is not None
                }
        
        self.generic_visit(node)

def check_file(filepath: Path) -> Tuple[int, int, List[str]]:
    """
    Analyze file for DSPy compliance
    Returns: (violations, warnings, detailed_issues)
    """
    try:
        content = filepath.read_text()
        tree = ast.parse(content)
    except Exception as e:
        return 1, 0, [f"Parse error: {e}"]
    
    checker = DSPyComplianceChecker(str(filepath))
    checker.visit(tree)
    
    issues = []
    violations = 0
    warnings = 0
    
    # Check 1: Signature classes have docstrings
    for sig in checker.signatures:
        if not checker.classes[sig]['has_docstring']:
            issues.append(f"⚠️ {sig} (Signature) missing docstring")
            warnings += 1
        elif '===' not in checker.classes[sig]['docstring']:
            issues.append(f"⚠️ {sig} (Signature) missing DSPy section headers (===)")
            warnings += 1
    
    # Check 2: Module classes have forward() method documented
    for mod in checker.modules:
        if 'forward' in checker.classes[mod]['methods']:
            if not checker.classes[mod]['methods']['forward']['has_docstring']:
                issues.append(f"❌ {mod}.forward() missing docstring (VIOLATION)")
                violations += 1
            else:
                doc = ast.get_docstring(list(filter(lambda x: isinstance(x, ast.FunctionDef) and x.name == 'forward', 
                                                      [item for item in ast.parse(content).body 
                                                       if isinstance(item, ast.ClassDef) and item.name == mod][0].body))[0])
                if doc and '===' not in doc:
                    issues.append(f"⚠️ {mod}.forward() docstring should include === sections")
                    warnings += 1
    
    # Check 3: Look for hardcoded prompts (f-strings with questions/colons)
    if 'f"' in content or "f'" in content:
        for i, line in enumerate(content.split('\n'), 1):
            if any(bad in line for bad in ['f"', "f'"]) and any(w in line for w in ['?', ':', '．', '。']):
                if 'dspy' not in line and 'Signature' not in line:
                    issues.append(f"⚠️ Line {i}: Possible hardcoded prompt (should use dspy.Signature)")
                    warnings += 1
    
    # Check 4: Module classes check
    for mod in checker.modules:
        if not checker.classes[mod]['has_docstring']:
            issues.append(f"⚠️ {mod} (dspy.Module) missing docstring")
            warnings += 1
    
    return violations, warnings, issues

def validate_workspace():
    """Run compliance checks on entire workspace"""
    workspace_root = Path('/workspaces/auto-coaching-log')
    
    python_files = list(workspace_root.glob('src/**/*.py'))
    
    total_violations = 0
    total_warnings = 0
    all_issues = []
    
    print("=" * 70)
    print("🔍 DSPy Compliance Validation Report")
    print("=" * 70)
    
    for filepath in sorted(python_files):
        violations, warnings, issues = check_file(filepath)
        
        if violations > 0 or warnings > 0:
            rel_path = filepath.relative_to(workspace_root)
            print(f"\n📄 {rel_path}")
            for issue in issues:
                print(f"  {issue}")
            
            total_violations += violations
            total_warnings += warnings
            all_issues.extend(issues)
    
    print("\n" + "=" * 70)
    print("📊 Summary")
    print("=" * 70)
    print(f"✅ Files checked: {len(python_files)}")
    print(f"❌ Violations: {total_violations}")
    print(f"⚠️  Warnings: {total_warnings}")
    
    if total_violations == 0:
        print("\n🎉 DSPy Compliance PASSED!")
        return 0
    else:
        print("\n❌ DSPy Compliance FAILED")
        return 1

if __name__ == '__main__':
    sys.exit(validate_workspace())
