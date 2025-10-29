from __future__ import annotations

import os
import time
from typing import List, Dict, Callable, Any, Optional
import socket
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    from tqdm import tqdm  # progress bar
except Exception:
    tqdm = None

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
    """Update check counts for successfully validated proxies."""
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

    # Update counts for all unique successfully validated proxies
    updated_count = 0
    for p in unique_proxies:
        old_count = counts.get(p, 0)
        counts[p] = old_count + 1
        updated_count += 1
    
    if updated_count > 0:
        _save_check_counts(counts)
        log(f"📈 Updated check counts for {updated_count} successfully validated proxies")


def _write_top100_by_checks(active_proxies: List[str]) -> None:
    """Write top 100 most frequently checked proxies to iran_top100_checked.txt."""
    try:
        counts = _load_check_counts()
        
        if not active_proxies:
            log("⚠️ No active proxies to rank")
            return
            
        # Score each active proxy by its check count (default 0)
        scored = [(counts.get(p, 0), idx, p) for idx, p in enumerate(active_proxies)]
        # Sort by count desc, then by original order asc (stable tie-break)
        scored.sort(key=lambda t: (-t[0], t[1]))
        
        # Get top 100
        top = [p for _, _, p in scored[:100]]
        
        # Log some statistics
        if scored:
            max_checks = scored[0][0] if scored else 0
            min_checks = scored[-1][0] if scored else 0
            avg_checks = sum(count for count, _, _ in scored) / len(scored) if scored else 0
            
            log(f"📊 Check count stats: max={max_checks}, min={min_checks}, avg={avg_checks:.1f}")
        
        write_text_file_atomic(TOP100_FILE, top)
        log(f"🏆 Wrote top {len(top)} most reliable proxies to {TOP100_FILE}")
        
        # Show top 5 for verification
        if top:
            log("🥇 Top 5 most reliable proxies:")
            for i, proxy in enumerate(top[:5], 1):
                check_count = counts.get(proxy, 0)
                log(f"  {i}. [{check_count} checks] {proxy[:60]}...")
                
    except Exception as e:
        log(f"❌ Failed to write top100 checked proxies: {e}")


def _validate_proxies_directly(proxies: List[str]) -> List[str]:
    """Validate proxies directly (no pipeline, no rewriting). Returns successes."""
    try:
        from . import net as net_module
    except Exception as e:
        log(f"❌ Failed to import net module: {e}")
        return []

    successful_proxies: List[str] = []
    total_proxies = len(proxies)

    log(f"🔍 Starting direct validation of {total_proxies} proxies...")

    # Concurrency level (tunable via env var)
    # Align concurrency with main pipeline's Stage 3 default
    try:
        from . import constants as C
        default_workers = int(getattr(C, 'STAGE3_WORKERS', 32))
    except Exception:
        default_workers = 32
    try:
        max_workers = max(1, int(os.environ.get('OPENRAY_IRAN_CONCURRENCY', str(default_workers))))
    except Exception:
        max_workers = default_workers

    if total_proxies == 0:
        return successful_proxies

    progress = tqdm(total=total_proxies, desc="Checking", unit="proxy") if tqdm else None

    def _update_progress(n: int = 1):
        if progress is not None:
            try:
                progress.update(n)
            except Exception:
                pass

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {executor.submit(net_module.validate_with_v2ray_core, proxy, 12): proxy for proxy in proxies if proxy}
        for future in as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            ok = False
            try:
                ok = bool(future.result())
            except Exception:
                ok = False
            if ok:
                successful_proxies.append(proxy)
            _update_progress(1)

    if progress is not None:
        try:
            progress.close()
        except Exception:
            pass

    log(f"🎯 Direct validation complete: {len(successful_proxies)}/{total_proxies} proxies are working")
    return successful_proxies


def check_internet_socket(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False


def _check_all_proxies_from_input() -> List[str]:
    """Load all proxies from all_valid_proxies.txt (no rewriting)."""
    # Load all proxies from the input file
    all_proxies: List[str] = []
    if os.path.exists(INPUT_FILE):
        all_proxies = [ln.strip() for ln in read_lines(INPUT_FILE) if ln.strip()]
        log(f"📋 Loaded {len(all_proxies)} proxies from {INPUT_FILE}")
    else:
        log(f"❌ Input file not found: {INPUT_FILE}")
        return []
    
    if not all_proxies:
        log("⚠️ No proxies to check")
        return []
    return all_proxies

def main() -> int:
    _seed_available_from_input()

    # Simple connectivity pre-check (no patching, no monitoring to avoid scope issues)
    if not _robust_internet_check():
        log("❌ No internet connection available")
        return 1

    try:
        log("🚀 Starting Iran proxy validation (direct, no rewriting)...")

        # Load proxies from main list without rewriting
        all_proxies = _check_all_proxies_from_input()
        if not all_proxies:
            log("❌ No proxies to check")
            return 1

        # First, drop stale entries not in current list
        _cleanup_check_counts(all_proxies)

        # Validate directly and count only successes
        successful_proxies = _validate_proxies_directly(all_proxies)
        if not successful_proxies:
            log("⚠️ No working proxies found this run")

        # Update counts only for successful proxies
        _update_check_counts_for_proxies(successful_proxies, all_proxies)

        # Generate top 100 ranking among existing proxies
        _write_top100_by_checks(all_proxies)

        log("✅ Completed: counts updated and top100 generated (no file rewrites)")
        return 0

    except Exception as e:
        log(f"❌ Proxy validation failed: {e}")
        return 1


if __name__ == '__main__':
    if _robust_internet_check():
        print("✅ Internet connection is available")
        raise SystemExit(main())
    else:
        print("❌ No internet connection")
