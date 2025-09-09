#!/usr/bin/env python3
"""
Script to clean proxy files by removing Git merge conflicts and duplicates
"""

import os
import re
from collections import Counter

def clean_file(file_path, output_path=None):
    """Clean a proxy file by removing Git conflicts and duplicates"""
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return False

    print(f"\n🔧 Cleaning {os.path.basename(file_path)}...")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        print(f"Original lines: {len(lines)}")

        # Step 1: Remove Git merge conflict markers and their content
        cleaned_lines = []
        skip_until_next = False

        for line in lines:
            stripped = line.strip()

            # Check for Git merge conflict markers
            if stripped == "<<<<<<< Updated upstream" or stripped == "=======" or stripped == ">>>>>>> Stashed changes":
                skip_until_next = True
                continue
            elif skip_until_next and (stripped == "<<<<<<< Updated upstream" or stripped == "======="):
                continue
            elif skip_until_next and stripped == ">>>>>>> Stashed changes":
                skip_until_next = False
                continue
            elif skip_until_next:
                continue
            else:
                cleaned_lines.append(line)

        print(f"After removing Git conflicts: {len(cleaned_lines)}")

        # Step 2: Remove empty lines and strip whitespace
        cleaned_lines = [line.strip() for line in cleaned_lines if line.strip()]
        print(f"After removing empty lines: {len(cleaned_lines)}")

        # Step 3: Remove duplicates while preserving order
        seen = set()
        unique_lines = []

        for line in cleaned_lines:
            if line not in seen:
                seen.add(line)
                unique_lines.append(line)

        print(f"After removing duplicates: {len(unique_lines)}")

        # Step 4: Validate proxy URLs (basic validation)
        valid_proxies = []
        invalid_count = 0

        for line in unique_lines:
            # Basic validation - proxy URLs should start with known protocols
            if any(line.startswith(protocol) for protocol in ['vmess://', 'vless://', 'trojan://', 'ss://', 'socks5://', 'http://', 'https://']):
                valid_proxies.append(line)
            else:
                invalid_count += 1
                if invalid_count <= 5:  # Show first 5 invalid lines
                    print(f"⚠️  Removed invalid proxy: {line[:100]}...")

        if invalid_count > 5:
            print(f"⚠️  Removed {invalid_count - 5} more invalid proxies")

        print(f"Valid proxies: {len(valid_proxies)}")

        # Step 5: Save cleaned file
        if output_path is None:
            output_path = file_path

        with open(output_path, 'w', encoding='utf-8') as f:
            for proxy in valid_proxies:
                f.write(proxy + '\n')

        print(f"✅ Saved cleaned file: {output_path}")
        return True

    except Exception as e:
        print(f"❌ Error cleaning {file_path}: {e}")
        return False

def analyze_duplicates(file_path):
    """Analyze duplicates in a cleaned file"""
    if not os.path.exists(file_path):
        return 0, 0, 0

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        proxies = [line.strip() for line in lines if line.strip()]

        # Count occurrences
        counts = Counter(proxies)
        duplicates = {proxy: count for proxy, count in counts.items() if count > 1}

        return len(proxies), len(counts), len(duplicates)

    except Exception as e:
        print(f"❌ Error analyzing {file_path}: {e}")
        return 0, 0, 0

def main():
    """Main function to clean both proxy files"""
    print("🧹 Cleaning proxy files...")

    # File paths
    main_file = "/mnt/d/projects/OpenRay/output/all_valid_proxies.txt"
    iran_file = "/mnt/d/projects/OpenRay/output_iran/all_valid_proxies_for_iran.txt"

    # Backup original files
    print("\n📦 Creating backups...")
    if os.path.exists(main_file):
        os.rename(main_file, main_file + ".backup")
        print(f"✅ Backup created: {main_file}.backup")

    if os.path.exists(iran_file):
        os.rename(iran_file, iran_file + ".backup")
        print(f"✅ Backup created: {iran_file}.backup")

    # Clean main proxy file
    if os.path.exists(main_file + ".backup"):
        success_main = clean_file(main_file + ".backup", main_file)

        if success_main:
            total_main, unique_main, dup_main = analyze_duplicates(main_file)
            print("\n📊 MAIN FILE RESULTS:")
            print(f"  Total proxies: {total_main}")
            print(f"  Unique proxies: {unique_main}")
            print(f"  Duplicates: {dup_main}")

    # Clean Iran proxy file
    if os.path.exists(iran_file + ".backup"):
        success_iran = clean_file(iran_file + ".backup", iran_file)

        if success_iran:
            total_iran, unique_iran, dup_iran = analyze_duplicates(iran_file)
            print("\n📊 IRAN FILE RESULTS:")
            print(f"  Total proxies: {total_iran}")
            print(f"  Unique proxies: {unique_iran}")
            print(f"  Duplicates: {dup_iran}")

    print("\n" + "="*60)
    print("CLEANUP SUMMARY")
    print("="*60)

    if 'total_main' in locals() and 'total_iran' in locals():
        print(f"✅ all_valid_proxies.txt: {total_main} valid unique proxies")
        print(f"✅ all_valid_proxies_for_iran.txt: {total_iran} valid unique proxies")
        print("\n🎉 Cleanup completed successfully!")
        print("📝 Backups saved with .backup extension")
    else:
        print("❌ Cleanup failed - check errors above")

if __name__ == "__main__":
    main()
