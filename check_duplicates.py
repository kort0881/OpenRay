#!/usr/bin/env python3
"""
Script to check for duplicated proxies in proxy files
"""

import os
import sys

# Add src directory to path so we can import our functions
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from common import get_proxy_connection_hash
except ImportError as e:
    print(f"❌ Failed to import proxy functions: {e}")
    sys.exit(1)

def check_duplicates(file_path, file_name):
    """Check for duplicate proxies in a file"""
    print(f"\nChecking {file_name}...")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Remove empty lines and strip whitespace
        proxies = [line.strip() for line in lines if line.strip()]

        total_proxies = len(proxies)
        print(f"Total proxies found: {total_proxies}")

        # Check for duplicates using connection-based hashing
        # This detects duplicates even when ps (remark) field differs
        seen_hashes = {}
        duplicates = []

        for proxy in proxies:
            conn_hash = get_proxy_connection_hash(proxy)
            if conn_hash in seen_hashes:
                # Found a duplicate
                original = seen_hashes[conn_hash]
                duplicates.append((proxy, original))
            else:
                seen_hashes[conn_hash] = proxy

        unique_proxies = len(seen_hashes)
        duplicate_count = len(duplicates)

        print(f"Unique proxies (connection-based): {unique_proxies}")
        print(f"Duplicate proxies: {duplicate_count}")

        if duplicate_count > 0:
            print(f"\n⚠️  FOUND {duplicate_count} DUPLICATED PROXIES in {file_name}")
            print("\nFirst 10 duplicated proxies:")
            for i, (dup, original) in enumerate(duplicates[:10]):
                print(f"  {i+1}. Duplicate: {dup[:80]}...")
                print(f"      Original:  {original[:80]}...")
        else:
            print(f"✅ No duplicates found in {file_name}")

        return duplicate_count, total_proxies, unique_proxies

    except FileNotFoundError:
        print(f"❌ File not found: {file_path}")
        return 0, 0, 0
    except Exception as e:
        print(f"❌ Error reading {file_path}: {e}")
        return 0, 0, 0

def main():
    """Main function to check both proxy files"""
    print("🔍 Checking for duplicated proxies in proxy files...")

    # Get repository root
    repo_root = os.path.dirname(os.path.abspath(__file__))
    
    # Check main proxy file
    main_file = os.path.join(repo_root, "output", "all_valid_proxies.txt")
    dup_main, total_main, unique_main = check_duplicates(main_file, "all_valid_proxies.txt")

    # Check Iran proxy file
    iran_file = os.path.join(repo_root, "output_iran", "all_valid_proxies_for_iran.txt")
    dup_iran, total_iran, unique_iran = check_duplicates(iran_file, "all_valid_proxies_for_iran.txt")

    # Summary
    print("\n" + "="*60)
    print("SUMMARY:")
    print("="*60)
    print(f"all_valid_proxies.txt: {total_main} total, {unique_main} unique, {dup_main} duplicates")
    print(f"all_valid_proxies_for_iran.txt: {total_iran} total, {unique_iran} unique, {dup_iran} duplicates")

    total_dup = dup_main + dup_iran
    if total_dup == 0:
        print("\n🎉 SUCCESS: No duplicated proxies found in either file!")
    else:
        print(f"\n⚠️  WARNING: Found {total_dup} total duplicated proxies across both files!")

if __name__ == "__main__":
    main()
