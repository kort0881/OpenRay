from __future__ import annotations

import os
import time
from typing import List, Dict, Callable, Any, Optional
import socket
import json
import threading

# Patch constants BEFORE importing modules that read them
from . import constants as C

# Determine input proxies file (existing curated list)
INPUT_FILE = os.path.join(C.REPO_ROOT, 'output', 'all_valid_proxies.txt')

# Redirect state and output to Iran-specific locations
C.STATE_DIR = os.path.join(C.REPO_ROOT, '.state_iran')
C.OUTPUT_DIR = os.path.join(C.REPO_ROOT, 'output_iran')

# Recompute dependent constant paths
C.TESTED_FILE = os.path.join(C.STATE_DIR, 'tested.txt')
C.AVAILABLE_FILE = os.path.join(C.OUTPUT_DIR, 'all_valid_proxies_for_iran.txt')
C.STREAKS_FILE = os.path.join(C.STATE_DIR, 'streaks.json')
C.KIND_DIR = os.path.join(C.OUTPUT_DIR, 'kind')
C.COUNTRY_DIR = os.path.join(C.OUTPUT_DIR, 'country')

# Provide an empty sources file so the main pipeline skips fetching new sources
EMPTY_SOURCES = os.path.join(C.REPO_ROOT, 'sources_iran.txt')
C.SOURCES_FILE = EMPTY_SOURCES

# Override Iran-specific settings
# Disable rechecking existing proxies for Iran (set to '0' to disable)
os.environ['OPENRAY_RECHECK_EXISTING'] = '1'

# Set NEW_URIS_LIMIT to a lower value for Iran-specific processing
C.NEW_URIS_LIMIT = 10000  # Reduced from default 25000 for Iran-specific processing

# Iran-specific check count tracking files
CHECK_COUNTS_FILE = os.path.join(C.STATE_DIR, 'check_counts.json')
TOP100_FILE = os.path.join(C.OUTPUT_DIR, 'iran_top100_checked.txt')

# Internet connectivity monitoring
INTERNET_CHECK_INTERVAL = 30  # Check connectivity every 30 seconds during proxy checking
INTERNET_RETRY_DELAY = 60    # Wait 60 seconds before retrying when internet is down
INTERNET_MONITORING_ACTIVE = False
LAST_INTERNET_CHECK = 0
INTERNET_STATUS = True

def _robust_internet_check(host="8.8.8.8", port=53, timeout=5) -> bool:
    """Robust internet connectivity check using multiple methods."""
    try:
        # Method 1: Socket connection to Google DNS
        socket.setdefaulttimeout(timeout)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            return True
    except Exception:
        pass

    try:
        # Method 2: Socket connection to Cloudflare DNS
        socket.setdefaulttimeout(timeout)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex(("1.1.1.1", 53))
        sock.close()
        if result == 0:
            return True
    except Exception:
        pass

    # Method 3: Try to resolve a well-known domain
    try:
        socket.gethostbyname("google.com")
        return True
    except Exception:
        pass

    return False

def _monitor_internet_connectivity():
    """Background thread to monitor internet connectivity."""
    global INTERNET_STATUS, LAST_INTERNET_CHECK

    while INTERNET_MONITORING_ACTIVE:
        current_time = time.time()

        # Only check if enough time has passed since last check
        if current_time - LAST_INTERNET_CHECK >= INTERNET_CHECK_INTERVAL:
            LAST_INTERNET_CHECK = current_time
            new_status = _robust_internet_check()

            if new_status != INTERNET_STATUS:
                if new_status:
                    log("✅ Internet connection restored")
                else:
                    log("❌ Internet connection lost - will retry in 60 seconds")
                INTERNET_STATUS = new_status

        time.sleep(5)  # Check every 5 seconds for responsiveness

def _start_internet_monitoring():
    """Start the background internet monitoring thread."""
    global INTERNET_MONITORING_ACTIVE

    if INTERNET_MONITORING_ACTIVE:
        return  # Already running

    INTERNET_MONITORING_ACTIVE = True
    monitor_thread = threading.Thread(target=_monitor_internet_connectivity, daemon=True)
    monitor_thread.start()
    log("Started internet connectivity monitoring")

def _stop_internet_monitoring():
    """Stop the background internet monitoring."""
    global INTERNET_MONITORING_ACTIVE
    INTERNET_MONITORING_ACTIVE = False
    log("Stopped internet connectivity monitoring")

def _wait_for_internet_with_retry(max_retries=10):
    """Wait for internet connection with retry logic."""
    global INTERNET_STATUS

    for attempt in range(max_retries):
        if INTERNET_STATUS:
            if attempt > 0:
                log(f"✅ Internet connection available after {attempt} checks")
            return True

        wait_time = INTERNET_RETRY_DELAY
        log(f"⏳ Waiting {wait_time} seconds for internet connection (attempt {attempt + 1}/{max_retries})")
        time.sleep(wait_time)

        # Force a fresh connectivity check
        INTERNET_STATUS = _robust_internet_check()

    log(f"❌ Failed to restore internet connection after {max_retries} attempts")
    return False

def _execute_with_connectivity_retry(func: Callable, *args, **kwargs) -> Any:
    """Execute a function with automatic retry on connectivity issues."""
    max_attempts = 3

    for attempt in range(max_attempts):
        try:
            if not INTERNET_STATUS:
                if not _wait_for_internet_with_retry(5):  # Wait up to 5 minutes
                    raise Exception("Internet connection unavailable")

            result = func(*args, **kwargs)
            return result

        except Exception as e:
            if "connection" in str(e).lower() or "timeout" in str(e).lower() or "unreachable" in str(e).lower():
                log(f"⚠️ Network error detected (attempt {attempt + 1}/{max_attempts}): {e}")
                INTERNET_STATUS = False  # Force connectivity recheck

                if attempt < max_attempts - 1:
                    if not _wait_for_internet_with_retry(3):  # Wait up to 3 minutes
                        continue
                else:
                    log(f"❌ Max retry attempts reached for: {e}")
                    raise e
            else:
                # Non-connectivity error, re-raise immediately
                raise e

    raise Exception("Max retry attempts reached")

def _patch_network_functions():
    """Patch network functions to include connectivity monitoring."""
    try:
        from . import net as net_module

        # Store original functions
        original_ping_host = net_module.ping_host
        original_connect_host_port = net_module.connect_host_port
        original_validate_with_v2ray_core = net_module.validate_with_v2ray_core
        original_fetch_urls_async_batch = net_module.fetch_urls_async_batch

        def _monitored_ping_host(host: str) -> bool:
            """Monitored ping_host with connectivity retry."""
            def _ping_operation():
                return original_ping_host(host)

            try:
                return _execute_with_connectivity_retry(_ping_operation)
            except Exception as e:
                log(f"⚠️ Ping failed for {host}: {e}")
                return False

        def _monitored_connect_host_port(host: str, port: int) -> bool:
            """Monitored connect_host_port with connectivity retry."""
            def _connect_operation():
                return original_connect_host_port(host, port)

            try:
                return _execute_with_connectivity_retry(_connect_operation)
            except Exception as e:
                log(f"⚠️ Connection failed for {host}:{port}: {e}")
                return False

        def _monitored_validate_with_v2ray_core(uri: str, timeout_s: int = 10) -> Optional[bool]:
            """Monitored validate_with_v2ray_core with connectivity retry."""
            def _validate_operation():
                return original_validate_with_v2ray_core(uri, timeout_s)

            try:
                return _execute_with_connectivity_retry(_validate_operation)
            except Exception as e:
                log(f"⚠️ V2Ray validation failed for {uri}: {e}")
                return False

        def _monitored_fetch_urls_async_batch(urls: List[str], timeout: int = 10) -> Dict[str, Optional[str]]:
            """Monitored fetch_urls_async_batch with connectivity retry."""
            def _fetch_operation():
                return original_fetch_urls_async_batch(urls, timeout)

            try:
                return _execute_with_connectivity_retry(_fetch_operation)
            except Exception as e:
                log(f"⚠️ URL fetch failed: {e}")
                return {url: None for url in urls}

        # Apply patches
        net_module.ping_host = _monitored_ping_host
        net_module.connect_host_port = _monitored_connect_host_port
        net_module.validate_with_v2ray_core = _monitored_validate_with_v2ray_core
        net_module.fetch_urls_async_batch = _monitored_fetch_urls_async_batch

        log("🔧 Applied network function patches for connectivity monitoring")

    except Exception as e:
        log(f"⚠️ Failed to patch network functions: {e}")

# Now import the rest of the pipeline after patching constants
from .common import log  # noqa: E402
from .io_ops import ensure_dirs, read_lines, write_text_file_atomic  # noqa: E402
from . import main as main_pipeline  # noqa: E402


def _seed_available_from_input() -> None:
    """Seed the Iran-specific AVAILABLE_FILE with contents of INPUT_FILE (if present)."""
    try:
        ensure_dirs()
        lines: List[str] = []
        if os.path.exists(INPUT_FILE):
            lines = [ln.strip() for ln in read_lines(INPUT_FILE) if ln.strip()]
        else:
            log(f"Input not found: {INPUT_FILE}")
        # write_text_file_atomic(C.AVAILABLE_FILE, lines)
        # Ensure empty sources file exists so main() doesn't exit
        try:
            if not os.path.exists(EMPTY_SOURCES):
                with open(EMPTY_SOURCES, 'w', encoding='utf-8') as f:
                    f.write('')
        except Exception:
            pass
    except Exception as e:
        log(f"Seeding available proxies failed: {e}")

def _load_check_counts() -> Dict[str, int]:
    try:
        if os.path.exists(CHECK_COUNTS_FILE):
            with open(CHECK_COUNTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # ensure keys are strings and values are ints
                    return {str(k): int(v) for k, v in data.items()}
    except Exception as e:
        log(f"Failed to load check counts: {e}")
    return {}


def _cleanup_check_counts(active_proxies: List[str]) -> None:
    """Remove check counts for proxies that are no longer active."""
    if not active_proxies:
        return

    counts = _load_check_counts()
    active_set = set(active_proxies)

    # Filter counts to only include active proxies
    cleaned_counts = {proxy: count for proxy, count in counts.items() if proxy in active_set}

    # Only save if there are changes
    if len(cleaned_counts) != len(counts):
        removed_count = len(counts) - len(cleaned_counts)
        log(f"Cleaned up check counts: removed {removed_count} inactive proxies")
        _save_check_counts(cleaned_counts)


def _save_check_counts(counts: Dict[str, int]) -> None:
    try:
        ensure_dirs()
        os.makedirs(os.path.dirname(CHECK_COUNTS_FILE), exist_ok=True)
        tmp = CHECK_COUNTS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8', errors='ignore') as f:
            json.dump(counts, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CHECK_COUNTS_FILE)
    except Exception as e:
        log(f"Failed to save check counts: {e}")


def _update_check_counts_for_proxies(proxies: List[str], active_proxies: List[str] = None) -> None:
    if not proxies:
        return
    counts = _load_check_counts()

    # If active_proxies is provided, only update counts for active proxies
    active_set = set(active_proxies) if active_proxies else None

    # Deduplicate proxies using V2RayN-style connection-based uniqueness
    from .common import get_v2rayn_connection_key
    seen_keys: set = set()
    unique_proxies: List[str] = []
    
    for p in proxies:
        if not p:
            continue
        # Skip if proxy is not in active list (when provided)
        if active_set is not None and p not in active_set:
            continue
        
        # Deduplicate using V2RayN-style connection key
        conn_key = get_v2rayn_connection_key(p)
        if conn_key not in seen_keys:
            seen_keys.add(conn_key)
            unique_proxies.append(p)

    for p in unique_proxies:
        counts[p] = int(counts.get(p, 0)) + 1
    _save_check_counts(counts)


def _write_top100_by_checks(active_proxies: List[str]) -> None:
    try:
        counts = _load_check_counts()
        # Score each active proxy by its check count (default 0)
        scored = [(counts.get(p, 0), idx, p) for idx, p in enumerate(active_proxies)]
        # Sort by count desc, then by original order asc (stable tie-break)
        scored.sort(key=lambda t: (-t[0], t[1]))
        top = [p for _, _, p in scored[:100]]
        write_text_file_atomic(TOP100_FILE, top)
        log(f"Wrote top {len(top)} checked active proxies to {TOP100_FILE}")
    except Exception as e:
        log(f"Failed to write top100 checked proxies: {e}")


def check_internet_socket(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False


def main() -> int:
    _seed_available_from_input()

    # Start internet connectivity monitoring
    _start_internet_monitoring()

    # Patch network functions for connectivity monitoring
    _patch_network_functions()

    # Initial connectivity check
    global INTERNET_STATUS
    INTERNET_STATUS = _robust_internet_check()
    if not INTERNET_STATUS:
        log("⚠️ No initial internet connection - waiting for connection...")
        if not _wait_for_internet_with_retry(5):
            log("❌ Could not establish internet connection")
            _stop_internet_monitoring()
            return 1

    # Capture the list of proxies that will be rechecked by the main pipeline this run
    pre_existing: List[str] = []
    try:
        if os.path.exists(C.AVAILABLE_FILE):
            pre_existing = [ln.strip() for ln in read_lines(C.AVAILABLE_FILE) if ln.strip()]
    except Exception:
        pre_existing = []

    # Execute main pipeline with connectivity monitoring
    try:
        log("🚀 Starting proxy validation with internet connectivity monitoring...")
        rc = main_pipeline.main()
    except Exception as e:
        log(f"❌ Main pipeline failed: {e}")
        rc = 1
    finally:
        # Stop internet monitoring
        _stop_internet_monitoring()

    if rc == 0:
        # Build top 100 among currently active proxies
        try:
            active_now: List[str] = []
            if os.path.exists(C.AVAILABLE_FILE):
                active_now = [ln.strip() for ln in read_lines(C.AVAILABLE_FILE) if ln.strip()]

            # Clean up check counts to only include active proxies
            _cleanup_check_counts(active_now)

            # After pipeline finishes, update check counts for proxies that were revalidated
            # Only update counts for proxies that are still active
            _update_check_counts_for_proxies(pre_existing, active_now)

            _write_top100_by_checks(active_now)
            log("✅ Proxy validation completed successfully")
        except Exception as e:
            log(f"❌ Active proxies processing failed: {e}")
            rc = 1
    else:
        log(f"⚠️ Skipping check-count update and top100 generation due to pipeline return code {rc}")

    return rc


if __name__ == '__main__':
    if _robust_internet_check():
        print("✅ Internet connection is available")
        raise SystemExit(main())
    else:
        print("❌ No internet connection")
