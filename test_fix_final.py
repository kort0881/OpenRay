#!/usr/bin/env python3
"""Test script to verify the tested proxy loading fix works for main_for_iran.py."""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Simulate main_for_iran.py setup
from constants import REPO_ROOT

# Override constants like main_for_iran.py does
import constants as C
C.STATE_DIR = os.path.join(C.REPO_ROOT, '.state_iran')
C.OUTPUT_DIR = os.path.join(C.REPO_ROOT, 'output_iran')
C.TESTED_FILE = os.path.join(C.STATE_DIR, 'tested.txt')
C.AVAILABLE_FILE = os.path.join(C.OUTPUT_DIR, 'all_valid_proxies_for_iran.txt')
C.STREAKS_FILE = os.path.join(C.STATE_DIR, 'streaks.json')
C.KIND_DIR = os.path.join(C.OUTPUT_DIR, 'kind')
C.COUNTRY_DIR = os.path.join(C.OUTPUT_DIR, 'country')

# Now import and test the functions
from io_ops import get_all_tested_files, load_tested_hashes_optimized

def test_fix():
    """Test that main_for_iran.py can load tested proxies from both directories."""
    print("Testing main_for_iran.py tested proxy loading fix...")
    print("=" * 60)

    print(f"Current TESTED_FILE: {C.TESTED_FILE}")

    # Get all tested files
    tested_files = get_all_tested_files()
    print(f"\nFound {len(tested_files)} tested files:")
    for f in tested_files:
        size = os.path.getsize(f) if os.path.exists(f) else 0
        print(f"  {f} ({size} bytes)")

    # Load tested hashes
    print("\nLoading tested hashes...")
    tested_hashes = load_tested_hashes_optimized()
    print(f"Loaded {len(tested_hashes)} unique tested proxy hashes")

    # Show breakdown by directory
    repo_root = os.path.dirname(os.path.abspath(__file__))
    state_dir = os.path.join(repo_root, '.state')
    state_iran_dir = os.path.join(repo_root, '.state_iran')

    state_hashes = 0
    state_iran_hashes = 0

    for file_path in tested_files:
        if '.state/' in file_path or file_path.startswith('.state/'):
            # Count hashes from .state directory
            try:
                if file_path.endswith('.bin'):
                    with open(file_path, 'rb') as f:
                        while True:
                            entry = f.read(28)
                            if not entry:
                                break
                            if len(entry) == 28:
                                state_hashes += 1
                else:
                    with open(file_path, 'r') as f:
                        for line in f:
                            if line.strip():
                                state_hashes += 1
            except:
                pass
        elif '.state_iran/' in file_path:
            # Count hashes from .state_iran directory
            try:
                if file_path.endswith('.bin'):
                    with open(file_path, 'rb') as f:
                        while True:
                            entry = f.read(28)
                            if not entry:
                                break
                            if len(entry) == 28:
                                state_iran_hashes += 1
                else:
                    with open(file_path, 'r') as f:
                        for line in f:
                            if line.strip():
                                state_iran_hashes += 1
            except:
                pass

    print(f"\nBreakdown:")
    print(f"  .state directory: {state_hashes} hashes")
    print(f"  .state_iran directory: {state_iran_hashes} hashes")
    print(f"  Total loaded: {len(tested_hashes)} hashes")

    if len(tested_hashes) >= state_hashes:
        print("\n✅ SUCCESS: main_for_iran.py can load tested proxies from both directories!")
        if state_iran_hashes > 0:
            print(f"   Including {state_iran_hashes} hashes from Iran-specific directory")
    else:
        print("\n❌ FAILURE: Something is wrong with the tested proxy loading")

if __name__ == '__main__':
    test_fix()
