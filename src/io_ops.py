from __future__ import annotations

import json
import os
import hashlib
import struct
import time
from typing import Iterable, List, Set, Dict

# Dynamic constants handling for runtime overrides
import os
import sys

# Get repository root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Default values for standalone usage
DEFAULT_STATE_DIR = os.path.join(REPO_ROOT, '.state')
DEFAULT_OUTPUT_DIR = os.path.join(REPO_ROOT, 'output')
DEFAULT_TESTED_FILE = os.path.join(DEFAULT_STATE_DIR, 'tested.txt')
DEFAULT_AVAILABLE_FILE = os.path.join(DEFAULT_OUTPUT_DIR, 'all_valid_proxies.txt')
DEFAULT_STREAKS_FILE = os.path.join(DEFAULT_STATE_DIR, 'streaks.json')

def get_state_dir():
    """Get current STATE_DIR, checking for runtime overrides"""
    try:
        # Try to get from constants module if it's loaded
        if 'constants' in sys.modules:
            return sys.modules['constants'].STATE_DIR
        # Try relative import
        from . import constants as C
        return C.STATE_DIR
    except (ImportError, AttributeError):
        return DEFAULT_STATE_DIR

def get_output_dir():
    """Get current OUTPUT_DIR, checking for runtime overrides"""
    try:
        if 'constants' in sys.modules:
            return sys.modules['constants'].OUTPUT_DIR
        from . import constants as C
        return C.OUTPUT_DIR
    except (ImportError, AttributeError):
        return DEFAULT_OUTPUT_DIR

def get_available_file():
    """Get current AVAILABLE_FILE, checking for runtime overrides"""
    try:
        if 'constants' in sys.modules:
            return sys.modules['constants'].AVAILABLE_FILE
        from . import constants as C
        return C.AVAILABLE_FILE
    except (ImportError, AttributeError):
        return DEFAULT_AVAILABLE_FILE

def get_streaks_file():
    """Get current STREAKS_FILE, checking for runtime overrides"""
    try:
        if 'constants' in sys.modules:
            return sys.modules['constants'].STREAKS_FILE
        from . import constants as C
        return C.STREAKS_FILE
    except (ImportError, AttributeError):
        return DEFAULT_STREAKS_FILE

def get_tested_file():
    """Get current TESTED_FILE, checking for runtime overrides"""
    try:
        # Always check sys.modules first for runtime modifications
        if 'constants' in sys.modules:
            return sys.modules['constants'].TESTED_FILE
        # Fallback to relative import
        from . import constants as C
        return C.TESTED_FILE
    except (ImportError, AttributeError):
        return DEFAULT_TESTED_FILE

# For backward compatibility, set some globals
try:
    STATE_DIR = get_state_dir()
    OUTPUT_DIR = get_output_dir()
    AVAILABLE_FILE = get_available_file()
    STREAKS_FILE = get_streaks_file()
except:
    STATE_DIR = DEFAULT_STATE_DIR
    OUTPUT_DIR = DEFAULT_OUTPUT_DIR
    AVAILABLE_FILE = DEFAULT_AVAILABLE_FILE
    STREAKS_FILE = DEFAULT_STREAKS_FILE


def ensure_dirs() -> None:
    os.makedirs(get_state_dir(), exist_ok=True)
    os.makedirs(get_output_dir(), exist_ok=True)


def read_lines(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return [line.rstrip('\r\n') for line in f]


def append_lines(path: str, lines: Iterable[str]) -> None:
    if not lines:
        return
    with open(path, 'a', encoding='utf-8', errors='ignore') as f:
        for line in lines:
            f.write(line)
            if not line.endswith('\n'):
                f.write('\n')


def write_text_file_atomic(path: str, lines: List[str]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', errors='ignore') as f:
        for ln in lines:
            f.write(ln)
            f.write('\n')
    os.replace(tmp, path)


# Persistence helpers

def load_tested_hashes() -> Set[str]:
    tested: Set[str] = set()
    for line in read_lines(get_tested_file()):
        h = line.strip()
        if h:
            tested.add(h)
    return tested


def load_existing_available() -> Set[str]:
    existing: Set[str] = set()
    for line in read_lines(get_available_file()):
        s = line.strip()
        if s:
            existing.add(s)
    return existing


def load_streaks() -> Dict[str, Dict[str, int]]:
    try:
        if not os.path.exists(get_streaks_file()):
            return {}
        with open(get_streaks_file(), 'r', encoding='utf-8', errors='ignore') as f:
            data = json.load(f)
            if isinstance(data, dict):
                # Ensure numeric fields are ints
                cleaned: Dict[str, Dict[str, int]] = {}
                for host, obj in data.items():
                    if not isinstance(obj, dict):
                        continue
                    streak = int(obj.get('streak', 0))
                    last_test = int(obj.get('last_test', 0))
                    last_success = int(obj.get('last_success', 0))
                    cleaned[host] = {'streak': streak, 'last_test': last_test, 'last_success': last_success}
                return cleaned
    except Exception:
        pass
    return {}


def save_streaks(streaks: Dict[str, Dict[str, int]]) -> None:
    try:
        os.makedirs(get_state_dir(), exist_ok=True)
        streaks_file = get_streaks_file()
        tmp = streaks_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8', errors='ignore') as f:
            json.dump(streaks, f, ensure_ascii=False)
        os.replace(tmp, streaks_file)
    except Exception:
        # best-effort; ignore
        pass


# Optimized tested hashes storage using binary format
def get_tested_bin_file():
    return get_tested_file() + '.bin'

def hash_to_bytes(hash_str: str) -> bytes:
    """Convert hex hash string to 20 bytes."""
    return bytes.fromhex(hash_str)

def bytes_to_hash(hash_bytes: bytes) -> str:
    """Convert 20 bytes back to hex hash string."""
    return hash_bytes.hex()

def load_tested_hashes_optimized() -> Set[str]:
    """Load tested hashes from all tested files (multi-file support)."""
    # Check for rotation before loading
    if should_rotate_tested_file():
        print(f"File rotation needed before loading. Current file size: {os.path.getsize(get_current_tested_file()) / (1024 * 1024):.1f}MB")
        rotate_tested_file()

    tested: Set[str] = set()

    # Get all tested files
    tested_files = get_all_tested_files()

    # Try optimized binary format first for each file
    for tested_file in tested_files:
        bin_file = tested_file + '.bin'
        if os.path.exists(bin_file):
            try:
                with open(bin_file, 'rb') as f:
                    # Read file in chunks for memory efficiency
                    while True:
                        # Read timestamp (8 bytes) + hash (20 bytes) = 28 bytes per entry
                        entry = f.read(28)
                        if not entry:
                            break
                        if len(entry) != 28:
                            continue  # Skip malformed entries
                        timestamp, hash_bytes = struct.unpack('>Q20s', entry)
                        tested.add(bytes_to_hash(hash_bytes))
            except Exception:
                # Fallback to text format for this file if binary is corrupted
                try:
                    for line in read_lines(tested_file):
                        h = line.strip()
                        if h:
                            tested.add(h)
                except Exception:
                    pass  # Skip corrupted files
        else:
            # Load from text format
            try:
                for line in read_lines(tested_file):
                    h = line.strip()
                    if h:
                        tested.add(h)
            except Exception:
                pass  # Skip corrupted files

    # Only migrate to optimized format if we're loading from a single file
    # and the binary file doesn't already exist or is smaller than expected
    tested_bin_file = get_tested_bin_file()
    should_migrate = (
        tested and
        len(get_all_tested_files()) == 1 and  # Only migrate if loading from single file
        (not os.path.exists(tested_bin_file) or
         os.path.getsize(tested_bin_file) < len(tested) * 28 * 0.9)  # Allow 10% size variance
    )

    if should_migrate:
        try:
            migrate_to_optimized_format(tested)
        except Exception:
            pass  # Migration failure shouldn't break loading

    return tested

def migrate_to_optimized_format(hashes: Set[str]) -> None:
    """Migrate existing text format to optimized binary format."""
    if not hashes:
        return

    current_time = int(time.time())
    entries = []

    for hash_str in hashes:
        hash_str = hash_str.strip()
        if not hash_str:
            continue
        try:
            hash_bytes = hash_to_bytes(hash_str)
            entries.append(struct.pack('>Q20s', current_time, hash_bytes))
        except Exception as e:
            # Log invalid hashes but continue
            print(f"Warning: Skipping invalid hash: {hash_str[:16]}... ({e})")
            continue

    if entries:
        try:
            # Write all entries at once for better performance
            tested_bin_file = get_tested_bin_file()
            with open(tested_bin_file + '.tmp', 'wb') as f:
                f.write(b''.join(entries))
            os.replace(tested_bin_file + '.tmp', tested_bin_file)
            print(f"Successfully migrated {len(entries)} hashes to binary format")
        except Exception as e:
            print(f"Migration failed: {e}")
            pass  # Migration failure is non-critical

def append_tested_hashes_optimized(new_hashes: Iterable[str]) -> None:
    """Append new hashes to current active tested file with rotation support."""
    if not new_hashes:
        return

    # Check if we need to rotate first
    if should_rotate_tested_file():
        # Rotate immediately if current file is already at/over limit
        print(f"Current file is {os.path.getsize(get_current_tested_file()) / (1024 * 1024):.1f}MB >= 50MB, rotating...")
        rotate_tested_file()

    # Get current active file
    current_file = get_current_tested_file()
    bin_file = current_file + '.bin'

    # Load existing hashes to check for duplicates (from all files)
    existing_hashes = load_tested_hashes_optimized()
    current_time = int(time.time())
    new_entries = []

    for hash_str in new_hashes:
        hash_str = hash_str.strip()
        if not hash_str or hash_str in existing_hashes:
            continue

        try:
            hash_bytes = hash_to_bytes(hash_str)
            new_entries.append(struct.pack('>Q20s', current_time, hash_bytes))
            existing_hashes.add(hash_str)
        except Exception:
            continue  # Skip invalid hashes

    if new_entries:
        try:
            # Check file size before writing
            if os.path.exists(current_file):
                current_size_mb = os.path.getsize(current_file) / (1024 * 1024)
                # Estimate size increase (each entry is ~41 bytes in text format)
                estimated_new_size_mb = current_size_mb + (len(new_entries) * 41) / (1024 * 1024)

                if estimated_new_size_mb >= 50:
                    # Rotate to new file
                    new_file = rotate_tested_file()
                    current_file = new_file
                    bin_file = new_file + '.bin'

            with open(bin_file, 'ab') as f:
                for entry in new_entries:
                    f.write(entry)
        except Exception:
            # Fallback to text format
            try:
                # Check file size for text format too
                if os.path.exists(current_file):
                    current_size_mb = os.path.getsize(current_file) / (1024 * 1024)
                    # Estimate size increase (each hash is ~41 bytes)
                    estimated_new_size_mb = current_size_mb + (len(new_entries) * 41) / (1024 * 1024)

                    if estimated_new_size_mb >= 50:
                        # Rotate to new file
                        new_file = rotate_tested_file()
                        current_file = new_file

                append_lines(current_file, (h for h in new_hashes if h.strip()))
            except Exception as e:
                print(f"Failed to append hashes: {e}")

def cleanup_old_hashes(days_to_keep: int = 30) -> int:
    """Remove hashes older than specified days. Returns number of removed entries."""
    if not os.path.exists(get_tested_bin_file()):
        return 0

    cutoff_time = int(time.time()) - (days_to_keep * 24 * 60 * 60)
    kept_entries = []
    removed_count = 0

    try:
        tested_bin_file = get_tested_bin_file()
        with open(tested_bin_file, 'rb') as f:
            while True:
                entry = f.read(28)
                if not entry:
                    break
                if len(entry) != 28:
                    continue
                timestamp, hash_bytes = struct.unpack('>Q20s', entry)
                if timestamp >= cutoff_time:
                    kept_entries.append(entry)
                else:
                    removed_count += 1

        if removed_count > 0:
            # Rewrite file with only kept entries
            with open(tested_bin_file + '.tmp', 'wb') as f:
                for entry in kept_entries:
                    f.write(entry)
            os.replace(tested_bin_file + '.tmp', tested_bin_file)

    except Exception:
        pass  # Cleanup failure is non-critical

    return removed_count

def get_storage_stats() -> Dict[str, int]:
    """Get statistics about current storage usage."""
    stats = {
        'text_file_size': 0,
        'binary_file_size': 0,
        'text_entries': 0,
        'binary_entries': 0,
        'unique_hashes': 0
    }

    # Text file stats
    tested_file = get_tested_file()
    if os.path.exists(tested_file):
        stats['text_file_size'] = os.path.getsize(tested_file)
        try:
            with open(tested_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = [line.strip() for line in f if line.strip()]
                stats['text_entries'] = len(lines)
                stats['unique_hashes'] = len(set(lines))
        except Exception:
            pass

    # Binary file stats
    tested_bin_file = get_tested_bin_file()
    if os.path.exists(tested_bin_file):
        stats['binary_file_size'] = os.path.getsize(tested_bin_file)
        stats['binary_entries'] = stats['binary_file_size'] // 28  # 28 bytes per entry

    return stats


def get_current_tested_file() -> str:
    """Get the current active tested file (tested.txt, tested_1.txt, tested_2.txt, etc.)."""
    tested_file = get_tested_file()
    state_dir = os.path.dirname(tested_file)
    base_name = os.path.basename(tested_file)  # "tested.txt"

    # Find all tested files
    tested_files = []
    if os.path.exists(state_dir):
        for file in os.listdir(state_dir):
            if file.startswith("tested") and file.endswith(".txt"):
                tested_files.append(file)

    if not tested_files:
        # No files exist, return the base file
        return tested_file

    # Sort files to find the highest numbered one
    tested_files.sort(key=lambda x: int(x.split('_')[1].split('.')[0]) if '_' in x else 0)

    # Get the last (highest numbered) file
    current_file = tested_files[-1]
    return os.path.join(state_dir, current_file)


def should_rotate_tested_file(max_size_mb: int = 50) -> bool:
    """Check if current tested file should be rotated based on size."""
    current_file = get_current_tested_file()
    if not os.path.exists(current_file):
        return False
    size_mb = os.path.getsize(current_file) / (1024 * 1024)
    return size_mb >= max_size_mb


def rotate_tested_file() -> str:
    """Rotate to next numbered tested file. Returns the new file path."""
    current_file = get_current_tested_file()
    state_dir = os.path.dirname(current_file)
    tested_file = get_tested_file()
    base_name = os.path.basename(tested_file)  # "tested.txt"

    # Determine next file number
    if current_file == tested_file:
        next_file = os.path.join(state_dir, "tested_1.txt")
    else:
        # Extract number from current file (e.g., "tested_2.txt" -> 2)
        current_num = int(os.path.basename(current_file).split('_')[1].split('.')[0])
        next_num = current_num + 1
        next_file = os.path.join(state_dir, f"tested_{next_num}.txt")

    print(f"Rotated to new file: {os.path.basename(next_file)}")
    return next_file


def get_all_tested_files() -> List[str]:
    """Get all tested files in order (tested.txt, tested_1.txt, tested_2.txt, etc.)."""
    tested_file = get_tested_file()
    state_dir = os.path.dirname(tested_file)
    tested_files = []

    # Always check the main .state directory for tested files
    main_state_dir = os.path.join(os.path.dirname(state_dir), '.state')
    dirs_to_check = [state_dir]

    # If we're in a different state directory (like .state_iran), also check the main .state directory
    if state_dir != main_state_dir and os.path.exists(main_state_dir):
        dirs_to_check.append(main_state_dir)

    for check_dir in dirs_to_check:
        if os.path.exists(check_dir):
            for file in os.listdir(check_dir):
                if file.startswith("tested") and (file.endswith(".txt") or file.endswith(".txt.bin")):
                    # For binary files, remove the .bin extension to get the base name
                    base_file = file
                    if file.endswith(".bin"):
                        base_file = file[:-4]  # Remove .bin extension
                    file_path = os.path.join(check_dir, base_file)
                    # Avoid duplicates
                    if file_path not in tested_files:
                        tested_files.append(file_path)

    # Sort files by number (tested.txt first, then tested_1.txt, tested_2.txt, etc.)
    tested_files.sort(key=lambda x: int(os.path.basename(x).split('_')[1].split('.')[0]) if '_' in os.path.basename(x) else 0)

    return tested_files
