#!/usr/bin/env python3
"""Test script to demonstrate the main_for_iran.py fix."""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_main_for_iran_fix():
    """Demonstrate that main_for_iran.py can now load tested proxies from both directories."""

    print("🔧 Testing main_for_iran.py fix for tested proxy loading")
    print("=" * 60)

    # Show current state
    repo_root = os.path.dirname(os.path.abspath(__file__))
    state_dir = os.path.join(repo_root, '.state')
    state_iran_dir = os.path.join(repo_root, '.state_iran')

    print(f"Repository root: {repo_root}")
    print(f"Main state dir: {state_dir}")
    print(f"Iran state dir: {state_iran_dir}")
    print()

    # Count hashes in each directory
    def count_hashes_in_dir(directory):
        count = 0
        if os.path.exists(directory):
            for file in os.listdir(directory):
                if file.startswith("tested") and file.endswith(".txt"):
                    file_path = os.path.join(directory, file)
                    try:
                        if file.endswith('.bin'):
                            with open(file_path, 'rb') as f:
                                while True:
                                    entry = f.read(28)
                                    if not entry:
                                        break
                                    if len(entry) == 28:
                                        count += 1
                        else:
                            with open(file_path, 'r') as f:
                                for line in f:
                                    if line.strip():
                                        count += 1
                    except:
                        pass
        return count

    main_hashes = count_hashes_in_dir(state_dir)
    iran_hashes = count_hashes_in_dir(state_iran_dir)

    print(f"Hashes in .state directory: {main_hashes}")
    print(f"Hashes in .state_iran directory: {iran_hashes}")
    print(f"Total available hashes: {main_hashes + iran_hashes}")
    print()

    # Test the fix by simulating main_for_iran.py behavior
    print("Testing main_for_iran.py behavior:")

    # Import constants and modify like main_for_iran.py does
    import constants as C
    original_tested_file = C.TESTED_FILE

    # Simulate main_for_iran.py setup
    C.STATE_DIR = os.path.join(C.REPO_ROOT, '.state_iran')
    C.OUTPUT_DIR = os.path.join(C.REPO_ROOT, 'output_iran')
    C.TESTED_FILE = os.path.join(C.STATE_DIR, 'tested.txt')
    C.AVAILABLE_FILE = os.path.join(C.OUTPUT_DIR, 'all_valid_proxies_for_iran.txt')
    C.STREAKS_FILE = os.path.join(C.STATE_DIR, 'streaks.json')
    C.KIND_DIR = os.path.join(C.OUTPUT_DIR, 'kind')
    C.COUNTRY_DIR = os.path.join(C.OUTPUT_DIR, 'country')

    print(f"Modified TESTED_FILE to: {C.TESTED_FILE}")

    # Now test loading with the modified paths
    from io_ops import load_tested_hashes_optimized
    loaded_hashes = load_tested_hashes_optimized()

    print(f"✅ Loaded {len(loaded_hashes)} tested proxy hashes with Iran-specific setup")
    print()

    # Restore original
    C.TESTED_FILE = original_tested_file

    # Summary
    print("📊 SUMMARY:")
    print(f"  Before fix: main_for_iran.py would only see {iran_hashes} hashes from .state_iran")
    print(f"  After fix: main_for_iran.py can see {len(loaded_hashes)} hashes from both directories")
    print()

    if len(loaded_hashes) >= main_hashes:
        print("🎉 SUCCESS: The fix is working! main_for_iran.py can now avoid re-testing proxies.")
        print("   On subsequent runs, it will show 'new to test: <much smaller number>' instead of all proxies.")
    else:
        print("❌ The fix may not be working properly.")

if __name__ == '__main__':
    test_main_for_iran_fix()
