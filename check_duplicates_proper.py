#!/usr/bin/env python3
"""
Proper proxy deduplication script using connection-based uniqueness.
Only considers connection-defining parameters, ignores remarks and metadata.
"""

import os
import sys
from collections import defaultdict

# Add src directory to path so we can import our functions
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from common import normalize_proxy_uri, get_proxy_connection_hash
except ImportError as e:
    print(f"❌ Failed to import proxy normalization functions: {e}")
    sys.exit(1)


def deduplicate_proxies_connection_based(file_path, output_path=None):
    """
    Remove duplicate proxies based on connection-defining parameters only.
    Preserves the first occurrence of each unique connection configuration.
    """
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return False

    print(f"\n🔧 Deduplicating {os.path.basename(file_path)} (connection-based)...")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        print(f"Original lines: {len(lines)}")

        # Remove empty lines and strip whitespace
        proxies = [line.strip() for line in lines if line.strip()]
        print(f"Non-empty proxies: {len(proxies)}")

        # Group by connection hash
        connection_groups = defaultdict(list)
        for proxy in proxies:
            conn_hash = get_proxy_connection_hash(proxy)
            connection_groups[conn_hash].append(proxy)

        # Keep only one proxy per connection (preserve first occurrence)
        unique_proxies = []
        duplicates_found = 0

        for conn_hash, proxy_list in connection_groups.items():
            if len(proxy_list) > 1:
                duplicates_found += len(proxy_list) - 1
                print(f"⚠️  Connection hash {conn_hash[:8]}...: {len(proxy_list)} duplicates")
                # Show examples of duplicates (first few)
                for i, dup in enumerate(proxy_list[:3]):
                    print(f"    {i+1}. {dup[:100]}...")
                if len(proxy_list) > 3:
                    print(f"    ... and {len(proxy_list) - 3} more")

            # Keep the first proxy from each group
            unique_proxies.append(proxy_list[0])

        print(f"Unique connections: {len(unique_proxies)}")
        print(f"Duplicates removed: {duplicates_found}")

        # Save deduplicated file
        if output_path is None:
            output_path = file_path

        with open(output_path, 'w', encoding='utf-8') as f:
            for proxy in unique_proxies:
                f.write(proxy + '\n')

        print(f"✅ Saved deduplicated file: {output_path}")
        return True

    except Exception as e:
        print(f"❌ Error deduplicating {file_path}: {e}")
        return False


def analyze_connection_duplicates(file_path):
    """
    Analyze what types of duplicates exist in the file.
    """
    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        proxies = [line.strip() for line in lines if line.strip()]

        # Group by connection hash
        connection_groups = defaultdict(list)
        for proxy in proxies:
            conn_hash = get_proxy_connection_hash(proxy)
            connection_groups[conn_hash].append(proxy)

        # Analyze duplicates
        duplicate_groups = {k: v for k, v in connection_groups.items() if len(v) > 1}

        stats = {
            'total_proxies': len(proxies),
            'unique_connections': len(connection_groups),
            'duplicate_groups': len(duplicate_groups),
            'total_duplicates': sum(len(v) - 1 for v in duplicate_groups.values()),
            'largest_duplicate_group': max((len(v) for v in duplicate_groups.values()), default=0)
        }

        return stats, duplicate_groups

    except Exception as e:
        print(f"❌ Error analyzing {file_path}: {e}")
        return {}, {}


def show_normalization_examples(file_path, limit=5):
    """
    Show examples of how proxies are normalized.
    """
    if not os.path.exists(file_path):
        return

    print(f"\n🔍 NORMALIZATION EXAMPLES from {os.path.basename(file_path)}:")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        proxies = [line.strip() for line in lines if line.strip()]

        for i, proxy in enumerate(proxies[:limit]):
            normalized = normalize_proxy_uri(proxy)
            conn_hash = get_proxy_connection_hash(proxy)

            print(f"\n{i+1}. Connection Hash: {conn_hash[:16]}...")
            print(f"   Original: {proxy[:120]}...")
            print(f"   Normalized: {normalized[:120]}...")

            # Show if remark was removed
            if '#' in proxy and '#' not in normalized:
                print("   ✓ Remark removed for uniqueness")

    except Exception as e:
        print(f"❌ Error showing examples: {e}")


def main():
    """Main function to deduplicate proxy files using connection-based uniqueness."""
    print("🔧 OpenRay Connection-Based Proxy Deduplication")
    print("="*60)

    # File paths
    main_file = "/mnt/d/projects/OpenRay/output/all_valid_proxies.txt"
    iran_file = "/mnt/d/projects/OpenRay/output_iran/all_valid_proxies_for_iran.txt"

    # Show normalization examples first
    if os.path.exists(main_file):
        show_normalization_examples(main_file)

    # Deduplicate main file
    if os.path.exists(main_file):
        print(f"\n{'='*60}")
        print("MAIN FILE DEDUPLICATION")
        print('='*60)

        # Analyze before deduplication
        stats, duplicate_groups = analyze_connection_duplicates(main_file)
        if stats:
            print(f"📊 BEFORE:")
            print(f"  Total proxies: {stats['total_proxies']}")
            print(f"  Unique connections: {stats['unique_connections']}")
            print(f"  Duplicate groups: {stats['duplicate_groups']}")
            print(f"  Total duplicates: {stats['total_duplicates']}")
            print(f"  Largest duplicate group: {stats['largest_duplicate_group']}")

        # Create backup
        backup_file = main_file + ".connection_backup"
        if os.path.exists(main_file) and not os.path.exists(backup_file):
            import shutil
            shutil.copy2(main_file, backup_file)
            print(f"📦 Backup created: {backup_file}")

        # Deduplicate
        success_main = deduplicate_proxies_connection_based(main_file)

        if success_main:
            # Analyze after deduplication
            stats_after, _ = analyze_connection_duplicates(main_file)
            if stats_after:
                print(f"\n📊 AFTER:")
                print(f"  Total proxies: {stats_after['total_proxies']}")
                print(f"  Unique connections: {stats_after['unique_connections']}")
                print(f"  Duplicates removed: {stats['total_proxies'] - stats_after['total_proxies'] if stats else 0}")

    # Deduplicate Iran file
    if os.path.exists(iran_file):
        print(f"\n{'='*60}")
        print("IRAN FILE DEDUPLICATION")
        print('='*60)

        # Create backup
        backup_file = iran_file + ".connection_backup"
        if os.path.exists(iran_file) and not os.path.exists(backup_file):
            import shutil
            shutil.copy2(iran_file, backup_file)
            print(f"📦 Backup created: {backup_file}")

        success_iran = deduplicate_proxies_connection_based(iran_file)

    print(f"\n{'='*60}")
    print("DEDUPPLICATION SUMMARY")
    print('='*60)

    if 'success_main' in locals() and 'success_iran' in locals():
        print(f"✅ all_valid_proxies.txt: {'SUCCESS' if success_main else 'FAILED'}")
        print(f"✅ all_valid_proxies_for_iran.txt: {'SUCCESS' if success_iran else 'FAILED'}")
        print("\n🎉 Connection-based deduplication completed!")
        print("📝 Backups saved with .connection_backup extension")
        print("\n💡 Key improvements:")
        print("   • Only connection-defining parameters considered for uniqueness")
        print("   • Remarks, tags, and metadata ignored")
        print("   • Default values normalized")
        print("   • Preserves first occurrence of each unique connection")
    else:
        print("❌ Deduplication failed - check errors above")


if __name__ == "__main__":
    main()
