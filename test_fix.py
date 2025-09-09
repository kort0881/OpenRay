#!/usr/bin/env python3
"""Test script to verify the tested proxy loading fix."""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from io_ops import get_all_tested_files, load_tested_hashes_optimized

def test_fix():
    """Test that tested proxies are loaded from both directories."""
    print("Testing tested proxy loading fix...")
    print("=" * 50)

    # First test with default TESTED_FILE (should be .state/tested.txt)
    print("Test 1: Default TESTED_FILE")
    tested_files = get_all_tested_files()
    print(f"Found {len(tested_files)} tested files:")
    for f in tested_files:
        size = os.path.getsize(f) if os.path.exists(f) else 0
        print(f"  {f} ({size} bytes)")

    # Load tested hashes
    tested_hashes = load_tested_hashes_optimized()
    print(f"\nLoaded {len(tested_hashes)} unique tested proxy hashes")

    # Now test with Iran-specific TESTED_FILE
    print("\n" + "=" * 50)
    print("Test 2: Iran-specific TESTED_FILE (.state_iran/tested.txt)")

    # Temporarily modify TESTED_FILE to simulate main_for_iran.py
    import io_ops
    original_tested_file = io_ops.TESTED_FILE
    repo_root = os.path.dirname(os.path.abspath(__file__))
    iran_tested_file = os.path.join(repo_root, '.state_iran', 'tested.txt')
    io_ops.TESTED_FILE = iran_tested_file

    print(f"Modified TESTED_FILE to: {io_ops.TESTED_FILE}")

    # Test with Iran-specific path
    tested_files_iran = get_all_tested_files()
    print(f"Found {len(tested_files_iran)} tested files:")
    for f in tested_files_iran:
        size = os.path.getsize(f) if os.path.exists(f) else 0
        print(f"  {f} ({size} bytes)")

    # Load tested hashes with Iran-specific path
    tested_hashes_iran = load_tested_hashes_optimized()
    print(f"\nLoaded {len(tested_hashes_iran)} unique tested proxy hashes with Iran-specific path")

    # Restore original
    io_ops.TESTED_FILE = original_tested_file

    # Compare results
    print("\n" + "=" * 50)
    print("Comparison:")
    print(f"  Default path loaded: {len(tested_hashes)} hashes")
    print(f"  Iran path loaded: {len(tested_hashes_iran)} hashes")

    if len(tested_hashes_iran) > len(tested_hashes):
        print("✅ SUCCESS: Iran path loaded more hashes (including from both directories)!")
        improvement = len(tested_hashes_iran) - len(tested_hashes)
        print(f"   Improvement: +{improvement} hashes from combined directories")
    elif len(tested_hashes_iran) == len(tested_hashes):
        print("⚠️  WARNING: Same number of hashes loaded - fix may not be working as expected")
    else:
        print("❌ FAILURE: Iran path loaded fewer hashes than default path")

    # Check both directories separately for comparison
    repo_root = os.path.dirname(os.path.abspath(__file__))
    state_dir = os.path.join(repo_root, '.state')
    state_iran_dir = os.path.join(repo_root, '.state_iran')

    state_hashes = set()
    state_iran_hashes = set()

    # Count from main .state directory
    if os.path.exists(state_dir):
        for file in os.listdir(state_dir):
            if file.startswith("tested") and file.endswith(".txt"):
                file_path = os.path.join(state_dir, file)
                bin_file = file_path + '.bin'
                if os.path.exists(bin_file):
                    try:
                        with open(bin_file, 'rb') as f:
                            while True:
                                entry = f.read(28)
                                if not entry:
                                    break
                                if len(entry) == 28:
                                    timestamp, hash_bytes = __import__('struct').unpack('>Q20s', entry)
                                    hash_str = __import__('hashlib').sha1(hash_bytes).hexdigest()
                                    state_hashes.add(hash_str)
                    except:
                        pass

    # Count from .state_iran directory
    if os.path.exists(state_iran_dir):
        for file in os.listdir(state_iran_dir):
            if file.startswith("tested") and file.endswith(".txt"):
                file_path = os.path.join(state_iran_dir, file)
                bin_file = file_path + '.bin'
                if os.path.exists(bin_file):
                    try:
                        with open(bin_file, 'rb') as f:
                            while True:
                                entry = f.read(28)
                                if not entry:
                                    break
                                if len(entry) == 28:
                                    timestamp, hash_bytes = __import__('struct').unpack('>Q20s', entry)
                                    hash_str = __import__('hashlib').sha1(hash_bytes).hexdigest()
                                    state_iran_hashes.add(hash_str)
                    except:
                        pass

    print(f"\nBreakdown:")
    print(f"  Main .state directory: {len(state_hashes)} hashes")
    print(f"  .state_iran directory: {len(state_iran_hashes)} hashes")
    print(f"  Combined (should match loaded): {len(state_hashes | state_iran_hashes)} hashes")

    # Check if the fix is working
    if len(tested_hashes) == len(state_hashes | state_iran_hashes):
        print("\n✅ SUCCESS: Fix is working! All tested proxies are being loaded from both directories.")
    else:
        print("\n❌ FAILURE: There's still an issue with loading tested proxies.")

if __name__ == '__main__':
    test_fix()
