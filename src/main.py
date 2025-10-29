from __future__ import annotations

import concurrent.futures
import os
import time
from typing import Dict, List, Optional, Set, Tuple

from .common import log, progress, sha1_hex, get_proxy_connection_hash, get_v2rayn_connection_key, get_openray_dedup_key
import json
from .constants import (
    AVAILABLE_FILE,
    CONSECUTIVE_REQUIRED,
    FETCH_WORKERS,
    FETCH_TIMEOUT,
    PING_WORKERS,
    SOURCES_FILE,
    ENABLE_STAGE2,
    ENABLE_STAGE3,
    STAGE3_MAX,
    OUTPUT_DIR,
    STAGE3_WORKERS,
    NEW_URIS_LIMIT_ENABLED,
    NEW_URIS_LIMIT,
)
from .geo import _build_country_counters, _country_flag
from .grouping import regroup_available_by_country, write_grouped_outputs
from .io_ops import (
    append_lines,
    ensure_dirs,
    load_existing_available,
    load_streaks,
    load_tested_hashes,
    load_tested_hashes_optimized,
    append_tested_hashes_optimized,
    read_lines,
    save_streaks,
    write_text_file_atomic,
)
from .net import _get_country_code_for_host, ping_host, connect_host_port, quick_protocol_probe, validate_with_v2ray_core, fetch_urls_async_batch, get_country_codes_batch, check_one_sync, is_dynamic_host, check_pair
from .parsing import (
    _set_remark,
    extract_host,
    extract_port,
    extract_uris,
    maybe_decode_subscription,
    parse_source_line,
)


def _has_connectivity() -> bool:
    """Best-effort Internet connectivity check using IP-only probes to avoid DNS dependency."""
    try:
        probes = [('1.1.1.1', 443), ('8.8.8.8', 53)]
        for ip, port in probes:
            try:
                if ping_host(ip):
                    return True
            except Exception:
                pass
            try:
                if connect_host_port(ip, port):
                    return True
            except Exception:
                pass
    except Exception:
        return False
    return False


# Check counts functionality for main.py
CHECK_COUNTS_FILE = os.path.join(os.path.dirname(AVAILABLE_FILE), '.state', 'check_counts.json')
TOP100_FILE = os.path.join(os.path.dirname(AVAILABLE_FILE), 'main_top100_checked.txt')


def _load_check_counts() -> Dict[str, Dict[str, int]]:
    """Load check counts with dual counter system: {proxy: {"main": count, "iran": count}}"""
    try:
        if os.path.exists(CHECK_COUNTS_FILE):
            with open(CHECK_COUNTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Convert old format to new format if needed
                    result = {}
                    for proxy, value in data.items():
                        if isinstance(value, dict) and "main" in value and "iran" in value:
                            # New format
                            result[str(proxy)] = {
                                "main": int(value.get("main", 0)),
                                "iran": int(value.get("iran", 0))
                            }
                        else:
                            # Old format - convert to new format
                            result[str(proxy)] = {
                                "main": int(value) if isinstance(value, (int, str)) else 0,
                                "iran": 0
                            }
                    return result
    except Exception as e:
        log(f"Failed to load check counts: {e}")
    return {}


def _save_check_counts(counts: Dict[str, Dict[str, int]]) -> None:
    try:
        ensure_dirs()
        os.makedirs(os.path.dirname(CHECK_COUNTS_FILE), exist_ok=True)
        tmp = CHECK_COUNTS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8', errors='ignore') as f:
            json.dump(counts, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CHECK_COUNTS_FILE)
    except Exception as e:
        log(f"Failed to save check counts: {e}")


def _update_check_counts_for_proxies(proxies: List[str], counter_type: str = "main") -> None:
    """Update check counts for successfully validated proxies."""
    if not proxies:
        return
    counts = _load_check_counts()

    # Deduplicate proxies using custom OpenRay dedup key
    seen_keys: set = set()
    unique_proxies: List[str] = []
    
    for p in proxies:
        if not p:
            continue
        
        # Deduplicate using custom OpenRay dedup key
        conn_key = get_openray_dedup_key(p)
        if conn_key not in seen_keys:
            seen_keys.add(conn_key)
            unique_proxies.append(p)

    # Update counts for all unique successfully validated proxies
    updated_count = 0
    for p in unique_proxies:
        if p not in counts:
            counts[p] = {"main": 0, "iran": 0}
        
        old_count = counts[p].get(counter_type, 0)
        counts[p][counter_type] = old_count + 1
        updated_count += 1
    
    if updated_count > 0:
        _save_check_counts(counts)
        log(f"📈 Updated {counter_type} check counts for {updated_count} successfully validated proxies")


def _write_top100_by_checks(active_proxies: List[str]) -> None:
    """Write top 100 most frequently checked proxies to main_top100_checked.txt.
    Prioritizes main scores, then iran scores as tiebreaker."""
    try:
        counts = _load_check_counts()
        
        if not active_proxies:
            log("⚠️ No active proxies to rank")
            return
            
        # Score each active proxy by main count first, then iran count as tiebreaker
        scored = []
        for idx, p in enumerate(active_proxies):
            proxy_counts = counts.get(p, {"main": 0, "iran": 0})
            main_count = proxy_counts.get("main", 0)
            iran_count = proxy_counts.get("iran", 0)
            scored.append((main_count, iran_count, idx, p))
        
        # Sort by main count desc, then iran count desc, then original order asc (stable tie-break)
        scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
        
        # Get top 100
        top = [p for _, _, _, p in scored[:100]]
        
        # Log some statistics
        if scored:
            max_main = scored[0][0] if scored else 0
            max_iran = max(t[1] for t in scored) if scored else 0
            avg_main = sum(t[0] for t in scored) / len(scored) if scored else 0
            avg_iran = sum(t[1] for t in scored) / len(scored) if scored else 0
            
            log(f"📊 Main check stats: max={max_main}, avg={avg_main:.1f}")
            log(f"📊 Iran check stats: max={max_iran}, avg={avg_iran:.1f}")
        
        write_text_file_atomic(TOP100_FILE, top)
        log(f"🏆 Wrote top {len(top)} most reliable proxies to {TOP100_FILE}")
        
        # Show top 5 for verification
        if top:
            log("🥇 Top 5 most reliable proxies:")
            for i, proxy in enumerate(top[:5], 1):
                proxy_counts = counts.get(proxy, {"main": 0, "iran": 0})
                main_count = proxy_counts.get("main", 0)
                iran_count = proxy_counts.get("iran", 0)
                log(f"  {i}. [Main:{main_count}, Iran:{iran_count}] {proxy[:60]}...")
                
    except Exception as e:
        log(f"❌ Failed to write top100 checked proxies: {e}")


def main() -> int:
    ensure_dirs()
    if not os.path.exists(SOURCES_FILE):
        log(f"Sources file not found: {SOURCES_FILE}")
        return 1

    source_lines = [ln.strip() for ln in read_lines(SOURCES_FILE) if ln.strip() and not ln.strip().startswith('#')]
    log(f"Loaded {len(source_lines)} sources")

    # Pre-flight connectivity check to avoid destructive actions during outages
    if not _has_connectivity():
        log("No Internet connectivity detected; skipping network operations and leaving existing outputs unchanged.")
        return 2

    # Load streaks persistence
    streaks: Dict[str, Dict[str, int]] = load_streaks()

    # Optionally re-validate current available proxies to drop broken ones
    host_success_run: Dict[str, bool] = {}
    recheck_env = os.environ.get('OPENRAY_RECHECK_EXISTING', '1').strip().lower()
    do_recheck = recheck_env not in ('0', 'false', 'no')
    alive: List[str] = []
    host_map_existing: Dict[str, Optional[str]] = {}
    if do_recheck and os.path.exists(AVAILABLE_FILE):
        existing_lines = [ln.strip() for ln in read_lines(AVAILABLE_FILE) if ln.strip()]
        if existing_lines:
            from .parsing import extract_host as _extract_host_for_existing

            # Deduplicate existing proxies using custom OpenRay dedup rules
            seen_connection_keys = set()
            deduplicated_existing = []
            for u in existing_lines:
                conn_key = get_openray_dedup_key(u)
                if conn_key not in seen_connection_keys:
                    seen_connection_keys.add(conn_key)
                    deduplicated_existing.append(u)
            
            log(f"Deduplicated existing proxies: {len(deduplicated_existing)} unique out of {len(existing_lines)} total")
            existing_lines = deduplicated_existing

            host_map_existing = {u: _extract_host_for_existing(u) for u in existing_lines}
            items = [(u, h) for u, h in host_map_existing.items() if h]
            # initialize to False for tested hosts
            for _, h in items:
                if h not in host_success_run:
                    host_success_run[h] = False

            def check_existing(item: Tuple[str, str]) -> Optional[str]:
                u, h = item

                def _check_proxy_operation():
                    try:
                        # Quick ping check with very short timeout
                        if not ping_host(h):
                            return None
                        scheme = u.split('://', 1)[0].lower()
                        if scheme in ('vmess', 'vless', 'trojan', 'ss', 'ssr'):
                            p = extract_port(u)
                            if p is not None:
                                # Connect check with short timeout
                                ok = connect_host_port(h, int(p))
                                if not ok:
                                    return None
                                if int(ENABLE_STAGE2) == 1:
                                    # Protocol probe with short timeout
                                    return u if quick_protocol_probe(u, h, int(p)) else None
                                return u
                        return u
                    except Exception as e:
                        # Log any exceptions that occur
                        print(f"Warning: Exception checking proxy {h}: {e}", flush=True)
                        return None

                # Use timeout wrapper with hard 10-second limit per proxy
                import threading
                result = [None]
                exception = [None]

                def target():
                    try:
                        result[0] = _check_proxy_operation()
                    except Exception as e:
                        exception[0] = e

                thread = threading.Thread(target=target, daemon=True)
                thread.start()
                thread.join(10.0)  # Hard 10-second timeout per proxy

                if thread.is_alive():
                    print(f"Warning: Proxy {h} timed out after 10 seconds", flush=True)
                    return None

                if exception[0]:
                    raise exception[0]

                return result[0]

            with concurrent.futures.ThreadPoolExecutor(max_workers=PING_WORKERS) as pool:
                print("Start Stage 2 for existing proxies")
                for res in progress(pool.map(check_existing, items), total=len(items)):
                    if res is not None:
                        alive.append(res)
                        h = host_map_existing.get(res)
                        if h:
                            host_success_run[h] = True

            # Optional Stage 3: validate a subset of revalidated existing proxies with V2Ray core (if configured)
            if int(ENABLE_STAGE3) == 1 and alive:
                core_path = ''
                try:
                    from .constants import V2RAY_CORE_PATH  # local import to avoid circulars in some contexts
                    core_path = (V2RAY_CORE_PATH or '').strip()
                except Exception:
                    core_path = ''
                if not core_path:
                    log("Stage 3 enabled, but V2Ray/Xray core not found or OPENRAY_V2RAY_CORE is not set; skipping core validation for existing proxies.")
                else:
                    subset = alive # [:int(STAGE3_MAX)]
                    kept_subset: List[str] = []

                    def _core_check(u: str) -> Optional[str]:
                        try:
                            res = validate_with_v2ray_core(u, timeout_s=12)
                        except Exception:
                            return None
                        return u if res is True else None

                    workers = int(STAGE3_WORKERS)
                    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool2:
                        print("Start Stage 3 for existing proxies")
                        for r in progress(pool2.map(_core_check, subset), total=len(subset)):
                            if r is not None:
                                kept_subset.append(r)
                    # Merge: replace subset portion with validated ones
                    alive = kept_subset + alive[len(subset):]

            if len(alive) != len(existing_lines):
                # Outage-safe guard: avoid purging available file if connectivity appears down
                if len(existing_lines) > 0 and len(alive) == 0 and not _has_connectivity():
                    log("Suspected Internet outage during revalidation; keeping existing available proxies file unchanged.")
                else:
                    tmp_path = AVAILABLE_FILE + '.tmp'
                    with open(tmp_path, 'w', encoding='utf-8', errors='ignore') as f:
                        for u in alive:
                            f.write(u)
                            f.write('\n')
                    os.replace(tmp_path, AVAILABLE_FILE)
                    log(f"Revalidated existing available proxies: kept {len(alive)} of {len(existing_lines)}")
            else:
                log("Revalidated existing available proxies: all still reachable")

    # Load persistence early to filter as we parse
    tested_hashes = load_tested_hashes_optimized()
    existing_available = load_existing_available()

    # Fetch and process sources concurrently; deduplicate URIs and collect only new ones
    seen_connection_keys: Set[str] = set()
    new_uris: List[str] = []
    new_hashes: List[str] = []
    fetched_count = 0
    total_extracted = 0  # Track total URIs extracted from all sources
    # Parse sources and fetch asynchronously using aiohttp (fallbacks built-in)
    parsed_sources = []
    for line in source_lines:
        url, flags = parse_source_line(line)
        if not url:
            continue
        parsed_sources.append((url, flags))
    urls_only = [u for (u, _) in parsed_sources]
    content_map = {}
    log("Start fetching sources...")
    try:
        import asyncio  # type: ignore
        content_map = asyncio.run(fetch_urls_async_batch(urls_only, concurrency=int(FETCH_WORKERS), timeout=int(FETCH_TIMEOUT)))
    except Exception as e:
        log(f"Async fetch failed to run event loop; falling back to sequential urllib: {e}")
        # Fallback: sequential
        from .net import fetch_url as _fetch_url_sync  # local import to avoid circulars
        from .common import progress as _progress
        for u in _progress(urls_only, total=len(urls_only)):
            content_map[u] = _fetch_url_sync(u)

    for (url, flags) in parsed_sources:
        content = content_map.get(url)
        if content is None:
            continue
        fetched_count += 1
        decoded = maybe_decode_subscription(content, hinted_base64=flags.get('base64', False))
        for u in extract_uris(decoded):
            total_extracted += 1  # Count all URIs extracted from all sources
            # Use custom OpenRay dedup key for deduplication
            conn_key = get_openray_dedup_key(u)
            if conn_key not in seen_connection_keys:
                seen_connection_keys.add(conn_key)
                h = get_proxy_connection_hash(u)  # Still use original hash for tested_hashes
                if h not in tested_hashes:
                    new_uris.append(u)
                    new_hashes.append(h)

    log(f"Fetched {fetched_count} contents")
    log(f"Extracted: {total_extracted} proxy URIs; Unique: {len(seen_connection_keys)} proxy URIs; New for testing: {len(new_uris)}")

    # Optionally limit the number of new URIs processed per run
    try:
        if int(NEW_URIS_LIMIT_ENABLED) == 1:
            _limit = int(NEW_URIS_LIMIT)
            if _limit > 0 and len(new_uris) > _limit:
                pre = len(new_uris)
                new_uris = new_uris[:_limit]
                new_hashes = new_hashes[:_limit]
                log(f"Limiting new URIs to {_limit} of {pre} due to NEW_URIS_LIMIT")
    except Exception:
        # On any misconfiguration, proceed without limiting
        pass

    # Extract hosts for new proxies
    host_map: Dict[str, Optional[str]] = {}
    for u in new_uris:
        host_map[u] = extract_host(u)
    to_test = [(u, host) for u, host in host_map.items() if host]
    log(f"New proxies with resolvable hosts: {len(to_test)}")

    # Stage 2 for new proxies: prefilter via fast batch ping, then connect/probe using asyncio or multiprocessing for large sets
    available_to_add: List[str] = []

    def check_one(item: Tuple[str, str]) -> Tuple[str, str, bool]:
        uri, host = item

        def _check_new_proxy_operation():
            try:
                # First, ensure host is reachable (ICMP/TCP fallback)
                if not ping_host(host):
                    return (uri, host, False)
                # Then, for TCP-based schemes, also ensure we can connect to the specific port
                scheme = uri.split('://', 1)[0].lower()
                if scheme in ('vmess', 'vless', 'trojan', 'ss', 'ssr'):
                    p = extract_port(uri)
                    if p is not None:
                        ok2 = connect_host_port(host, int(p))
                        if ok2 and int(ENABLE_STAGE2) == 1:
                            ok2 = quick_protocol_probe(uri, host, int(p))
                        return (uri, host, ok2)
                return (uri, host, True)
            except Exception:
                return (uri, host, False)

        # Use timeout wrapper with hard 10-second limit per proxy
        import threading
        result = [None]
        exception = [None]

        def target():
            try:
                result[0] = _check_new_proxy_operation()
            except Exception as e:
                exception[0] = e

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(10.0)  # Hard 10-second timeout per proxy

        if thread.is_alive():
            print(f"Warning: New proxy {host} timed out after 10 seconds", flush=True)
            return (uri, host, False)

        if exception[0]:
            return (uri, host, False)

        return result[0] if result[0] else (uri, host, False)

    with concurrent.futures.ThreadPoolExecutor(max_workers=PING_WORKERS) as pool:
        print("Start Stage 2 for new proxies")
        for uri, host, ok in progress(pool.map(check_one, to_test), total=len(to_test)):
            # Mark host as tested this run
            if host not in host_success_run:
                host_success_run[host] = False
            if ok:
                host_success_run[host] = True
                available_to_add.append(uri)

    log(f"Available proxies found this run (ping/connect ok): {len(available_to_add)}")

    # Optional Stage 3: validate a subset with V2Ray core (if configured)
    if int(ENABLE_STAGE3) == 1 and available_to_add:
        core_path = ''
        try:
            from .constants import V2RAY_CORE_PATH  # local import to avoid circulars in some contexts
            core_path = (V2RAY_CORE_PATH or '').strip()
        except Exception:
            core_path = ''
        if not core_path:
            log("Stage 3 enabled, but V2Ray/Xray core not found or OPENRAY_V2RAY_CORE is not set; skipping core validation.")
        else:
            subset = available_to_add # [:int(STAGE3_MAX)]
            kept_subset: List[str] = []

            def _core_check(u: str) -> Optional[str]:
                try:
                    res = validate_with_v2ray_core(u, timeout_s=12)
                except Exception:
                    return None
                return u if res is True else None

            workers = int(STAGE3_WORKERS)
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool2:
                print("Start Stage 3 for new proxies")
                for r in progress(pool2.map(_core_check, subset), total=len(subset)):
                    if r is not None:
                        kept_subset.append(r)
            # Merge: replace subset portion with validated ones
            available_to_add = kept_subset + available_to_add[len(subset):]

    # Deduplicate against existing available file and write (custom OpenRay dedup rules)
    new_available_unique: List[str] = []
    existing_connection_keys = {get_openray_dedup_key(u) for u in existing_available}
    for u in available_to_add:
        conn_key = get_openray_dedup_key(u)
        if conn_key not in existing_connection_keys:
            existing_connection_keys.add(conn_key)
            new_available_unique.append(u)

    if new_available_unique:
        # Build per-country counters from existing entries
        counters = _build_country_counters(existing_available)
        formatted_to_append: List[str] = []
        print("Start formatting new available proxies")
        # Batch resolve country codes for hosts of new entries
        hosts_to_resolve: List[str] = []
        for u in new_available_unique:
            h = host_map.get(u)
            if h:
                hosts_to_resolve.append(h)
        # Deduplicate while preserving order
        hosts_to_resolve = list(dict.fromkeys(hosts_to_resolve))
        cc_map: Dict[str, Optional[str]] = {}
        try:
            cc_map = get_country_codes_batch(hosts_to_resolve)
        except Exception as e:
            log(f"Batch geolocation failed; falling back per-host: {e}")
            for h in hosts_to_resolve:
                try:
                    cc_map[h] = _get_country_code_for_host(h)
                except Exception:
                    cc_map[h] = None
        for u in progress(new_available_unique, total=len(new_available_unique)):
            host = host_map.get(u)
            cc = cc_map.get(host) if host else None
            if not cc:
                cc = 'XX'
            flag = _country_flag(cc)
            next_num = counters.get(cc, 0) + 1
            counters[cc] = next_num
            # Determine dynamic status using DNS heuristic (no streaks used)
            is_dynamic = True if not host else is_dynamic_host(host)
            if is_dynamic:
                remark = f"[OpenRay] Dynamic-{next_num}"
            else:
                remark = f"[OpenRay] {flag} {cc}-{next_num}"
            new_u = _set_remark(u, remark)
            formatted_to_append.append(new_u)
        append_lines(AVAILABLE_FILE, formatted_to_append)
        log(f"Appended {len(formatted_to_append)} new available proxies to {AVAILABLE_FILE} with formatted remarks")
    else:
        log("No new available proxies to append (all duplicates)")

    # Regroup available proxies by country
    regroup_available_by_country()

    # Optional: export v2ray/xray JSON configs for available proxies
    try:
        exp_flag = os.environ.get('OPENRAY_EXPORT_V2RAY', '').strip().lower()
        if exp_flag in ('1', 'true', 'yes', 'on'):
            try:
                from .v2ray import export_v2ray_configs
                lines_for_export = [ln.strip() for ln in read_lines(AVAILABLE_FILE) if ln.strip()]
                written = export_v2ray_configs(lines_for_export)
                if written > 0:
                    log(f"Exported {written} v2ray/xray JSON configs to {os.path.join(OUTPUT_DIR, 'v2ray_configs')}")
                else:
                    log("V2Ray export requested, but no configs were generated (unsupported schemes?)")
            except Exception as e:
                log(f"V2Ray config export failed: {e}")
    except Exception:
        pass

    # Persist tested hashes (append all newly tested regardless of success)
    from .constants import TESTED_FILE

    append_tested_hashes_optimized(new_hashes)
    log(f"Recorded {len(new_hashes)} newly tested proxies to optimized storage")

    # Update streaks based on this run's host successes
    try:
        total_successes = sum(1 for v in host_success_run.values() if v)
        if total_successes == 0 and not _has_connectivity():
            log("Suspected Internet outage affected tests; skipping streaks update to avoid false resets.")
        else:
            now_ts = int(time.time())
            for host, success in host_success_run.items():
                rec = streaks.get(host, {'streak': 0, 'last_test': 0, 'last_success': 0})
                rec['last_test'] = now_ts
                if success:
                    rec['streak'] = int(rec.get('streak', 0)) + 1
                    rec['last_success'] = now_ts
                else:
                    rec['streak'] = 0
                streaks[host] = rec
            save_streaks(streaks)
    except Exception as e:
        log(f"Streaks update failed: {e}")

    # Update check counts for successfully validated proxies
    try:
        # Load current available proxies to update counts
        current_available = load_existing_available()
        if current_available:
            _update_check_counts_for_proxies(current_available, "main")
            _write_top100_by_checks(current_available)
    except Exception as e:
        log(f"Check counts update failed: {e}")

    # Generate grouped outputs by kind and country
    try:
        write_grouped_outputs()
    except Exception as e:
        log(f"Grouped outputs step failed: {e}")

    return 0


if __name__ == '__main__':
    import sys
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
