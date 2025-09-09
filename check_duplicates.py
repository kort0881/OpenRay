#!/usr/bin/env python3
"""
Script to check for duplicated proxies in proxy files
"""

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

        # Check for duplicates
        seen = set()
        duplicates = set()

        for proxy in proxies:
            if proxy in seen:
                duplicates.add(proxy)
            else:
                seen.add(proxy)

        unique_proxies = len(seen)
        duplicate_count = len(duplicates)

        print(f"Unique proxies: {unique_proxies}")
        print(f"Duplicate proxies: {duplicate_count}")

        if duplicate_count > 0:
            print(f"\n⚠️  FOUND {duplicate_count} DUPLICATED PROXIES in {file_name}")
            print("\nFirst 10 duplicated proxies:")
            for i, dup in enumerate(list(duplicates)[:10]):
                count = proxies.count(dup)
                print(f"  {i+1}. Appears {count} times: {dup[:100]}...")
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

    # Check main proxy file
    main_file = "/mnt/d/projects/OpenRay/output/all_valid_proxies.txt"
    dup_main, total_main, unique_main = check_duplicates(main_file, "all_valid_proxies.txt")

    # Check Iran proxy file
    iran_file = "/mnt/d/projects/OpenRay/output_iran/all_valid_proxies_for_iran.txt"
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
