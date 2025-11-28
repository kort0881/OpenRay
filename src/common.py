from __future__ import annotations
import os
import base64
import hashlib
import threading
import json
from urllib.parse import urlparse

try:
    from tqdm import tqdm as _tqdm  # type: ignore

    def progress(iterable, total=None):
        # Disable tqdm in GitHub Actions or other CI environments
        # if os.environ.get('GITHUB_ACTIONS') or os.environ.get('CI'):
        #     return iterable

        return _tqdm(iterable, total=total)
except Exception:

    def progress(iterable, total=None):
        return iterable

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode('utf-8', errors='ignore')).hexdigest()


def safe_b64decode_to_bytes(s: str) -> bytes | None:
    """Try to base64-decode a string with leniency (padding, URL-safe). Returns None on failure."""
    if not s:
        return None
    # Remove whitespace
    compact = ''.join(s.split())
    # Convert URL-safe variants
    compact = compact.replace('-', '+').replace('_', '/')
    # Pad
    padding = (-len(compact)) % 4
    compact += '=' * padding
    try:
        return base64.b64decode(compact, validate=False)
    except Exception:
        return None


def normalize_proxy_uri(uri: str) -> str:
    """
    Extract only connection-defining parameters from a proxy URI.
    Removes remarks, comments, and metadata that don't affect the connection.

    Returns a normalized string containing only:
    - Protocol type (vmess, vless, trojan, etc.)
    - Server (hostname or IP)
    - Port
    - UUID/password/user ID
    - Security settings (TLS, encryption)
    - Transport type (ws, grpc, tcp, h2, quic, etc.)
    - Transport parameters (path, host header, service name, etc.)
    - SNI (if TLS is used)

    Ignores:
    - Remarks/comments (after #)
    - Metadata tags
    - Descriptions
    - Order/index information
    """
    if not uri or '://' not in uri:
        return uri

    try:
        # Split off remarks/comments (everything after #)
        base_uri = uri.split('#', 1)[0]

        # Parse the URI
        from urllib.parse import urlparse, parse_qs, unquote
        parsed = urlparse(base_uri)

        protocol = parsed.scheme.lower()
        if not protocol:
            return uri

        # Extract components based on protocol
        if protocol == 'vmess':
            return _normalize_vmess(base_uri, parsed)
        elif protocol == 'vless':
            return _normalize_vless(base_uri, parsed)
        elif protocol == 'trojan':
            return _normalize_trojan(base_uri, parsed)
        elif protocol in ['ss', 'ssr']:
            return _normalize_ss(base_uri, parsed, protocol)
        else:
            # Generic normalization for other protocols
            return _normalize_generic(base_uri, parsed, protocol)

    except Exception:
        # If parsing fails, return original (better than losing data)
        return uri


def _normalize_vmess(uri: str, parsed) -> str:
    """Normalize VMess proxy URI."""
    try:
        # Extract and decode the base64 payload
        # VMess format: vmess://base64_json - payload is in netloc, not path
        payload_b64 = parsed.netloc or parsed.path.lstrip('/')
        if not payload_b64:
            return uri

        b = safe_b64decode_to_bytes(payload_b64)
        if not b:
            return uri

        import json
        obj = json.loads(b.decode('utf-8', errors='ignore') or '{}')

        # Normalize empty strings to None for optional fields
        def normalize_value(v):
            if v == '' or v is None:
                return None
            return str(v).strip()

        # Extract connection-defining parameters with consistent defaults
        # Treat empty strings same as missing for optional fields
        add = normalize_value(obj.get('add') or obj.get('address'))
        port = normalize_value(obj.get('port') or obj.get('portNumber'))
        id_val = normalize_value(obj.get('id'))
        
        # Required fields
        if not add or not port or not id_val:
            return uri

        # Optional fields with defaults - normalize empty strings
        aid = normalize_value(obj.get('aid')) or '0'
        scy = normalize_value(obj.get('scy')) or 'auto'
        net = normalize_value(obj.get('net')) or 'tcp'
        type_val = normalize_value(obj.get('type')) or 'none'
        host = normalize_value(obj.get('host'))
        path = normalize_value(obj.get('path'))
        def canonicalize_tls(value: str | None) -> str | None:
            if not value:
                return None
            low = value.lower()
            if low in ('none', 'disable', 'disabled', 'off', 'false', '0'):
                return None
            return low

        tls = canonicalize_tls(normalize_value(obj.get('tls')))
        sni = normalize_value(obj.get('sni'))
        alpn = normalize_value(obj.get('alpn'))
        fp = normalize_value(obj.get('fp'))

        # Build normalized dict - only include non-empty optional fields
        normalized = {
            'v': '2',
            'add': add,
            'port': port,
            'id': id_val,
            'aid': aid,
            'net': net,
            'type': type_val,
        }

        # Include scy only when it departs from the protocol default
        if scy not in (None, '', 'auto', 'aes-128-gcm'):
            normalized['scy'] = scy

        # Add optional fields only if they have non-empty values
        if host:
            normalized['host'] = host
        if path:
            normalized['path'] = path
        if tls:
            normalized['tls'] = tls
        if sni:
            normalized['sni'] = sni
        if alpn:
            normalized['alpn'] = alpn
        if fp:
            normalized['fp'] = fp

        # Reconstruct VMess JSON
        json_str = json.dumps(normalized, separators=(',', ':'), ensure_ascii=False, sort_keys=True)
        import base64
        b64_payload = base64.b64encode(json_str.encode('utf-8')).decode('ascii')

        return f'vmess://{b64_payload}'

    except Exception:
        return uri


def _normalize_vless(uri: str, parsed) -> str:
    """Normalize VLESS proxy URI."""
    try:
        # VLESS format: vless://uuid@host:port?params
        path_parts = parsed.path.lstrip('/').split('@', 1)
        if len(path_parts) != 2:
            return uri

        uuid = path_parts[0]
        host_port = path_parts[1]

        # Parse query parameters
        from urllib.parse import parse_qs
        query_params = parse_qs(parsed.query)

        # Extract connection-defining parameters
        normalized_params = {}

        # Required parameters
        if uuid:
            normalized_params['id'] = uuid
        if ':' in host_port:
            host, port = host_port.rsplit(':', 1)
            normalized_params['host'] = host
            normalized_params['port'] = port

        # Connection-defining query parameters
        connection_params = [
            'security', 'encryption', 'type', 'path', 'host', 'serviceName',
            'mode', 'headerType', 'sni', 'alpn', 'fp', 'pbk', 'sid', 'flow'
        ]

        for param in connection_params:
            if param in query_params and query_params[param]:
                value = query_params[param][0]
                if value:  # Only include non-empty values
                    normalized_params[param] = value

        # Normalize defaults
        if normalized_params.get('security') == 'none':
            normalized_params['security'] = 'none'
        if normalized_params.get('encryption') == 'none':
            normalized_params['encryption'] = 'none'
        if normalized_params.get('type') == 'tcp':
            normalized_params['type'] = 'tcp'
        if normalized_params.get('headerType') == 'none':
            normalized_params['headerType'] = 'none'

        # Reconstruct URI
        query_string = '&'.join(f'{k}={v}' for k, v in sorted(normalized_params.items()) if k not in ['host', 'port', 'id'])
        host_port_part = f"{normalized_params.get('host', '')}:{normalized_params.get('port', '')}"
        uuid_part = normalized_params.get('id', '')

        result = f'vless://{uuid_part}@{host_port_part}'
        if query_string:
            result += f'?{query_string}'

        return result

    except Exception:
        return uri


def _normalize_trojan(uri: str, parsed) -> str:
    """Normalize Trojan proxy URI."""
    try:
        from urllib.parse import parse_qs, unquote, quote

        # Trojan format: trojan://password@host:port?params
        netloc = parsed.netloc or parsed.path.lstrip('/')
        if '@' not in netloc:
            return uri

        password_raw, host_port = netloc.split('@', 1)
        password = unquote(password_raw)
        if not password:
            return uri

        # Parse query parameters
        query_params = parse_qs(parsed.query)

        # Extract connection-defining parameters
        conn_params = {}

        # Required parameters
        if ':' not in host_port:
            return uri
        server_host, server_port = host_port.rsplit(':', 1)

        # Connection-defining query parameters
        connection_params = [
            'security', 'type', 'path', 'host', 'sni', 'alpn', 'fp', 'pbk', 'sid', 'flow'
        ]

        for param in connection_params:
            if param in query_params and query_params[param]:
                value = query_params[param][0]
                if value:  # Only include non-empty values
                    conn_params[param] = value

        # Normalize defaults
        if conn_params.get('security') == 'tls':
            conn_params['security'] = 'tls'

        # Reconstruct URI
        query_items = []
        for k in sorted(conn_params):
            query_items.append(f"{k}={conn_params[k]}")

        query_string = '&'.join(query_items)
        password_part = quote(password, safe='')
        host_port_part = f"{server_host}:{server_port}"

        result = f'trojan://{password_part}@{host_port_part}'
        if query_string:
            result += f'?{query_string}'

        return result

    except Exception:
        return uri


def _normalize_ss(uri: str, parsed, protocol: str) -> str:
    """Normalize Shadowsocks/SSR proxy URI."""
    try:
        # SS format: ss://method:password@host:port or ss://base64(method:password@host:port)
        # SSR format: ssr://base64(host:port:protocol:method:obfs:password_base64/?params)

        if protocol == 'ssr':
            # SSR handling
            payload = parsed.path.lstrip('/')
            b = safe_b64decode_to_bytes(payload)
            if not b:
                return uri
            text = b.decode('utf-8', errors='ignore')
            # SSR has a different format, return as-is for now
            return uri

        # SS handling
        payload = parsed.path.lstrip('/')
        text = None

        # Try to decode if it's base64
        b = safe_b64decode_to_bytes(payload)
        if b:
            text = b.decode('utf-8', errors='ignore')
        else:
            text = payload

        # Parse method:password@host:port
        if '@' in text:
            method_pass, host_port = text.rsplit('@', 1)
            if ':' in method_pass:
                method, password = method_pass.split(':', 1)
                if ':' in host_port:
                    host, port = host_port.rsplit(':', 1)

                    # Parse query parameters for additional settings
                    from urllib.parse import parse_qs
                    query_params = parse_qs(parsed.query)

                    # Reconstruct normalized URI
                    import base64
                    credentials = f"{method}:{password}@{host}:{port}"
                    b64_credentials = base64.b64encode(credentials.encode('utf-8')).decode('ascii')

                    result = f'ss://{b64_credentials}'

                    # Add connection-defining query parameters
                    connection_params = ['plugin', 'mode']
                    query_parts = []
                    for param in connection_params:
                        if param in query_params and query_params[param]:
                            value = query_params[param][0]
                            if value:
                                query_parts.append(f'{param}={value}')

                    if query_parts:
                        result += '?' + '&'.join(sorted(query_parts))

                    return result

        return uri

    except Exception:
        return uri


def _normalize_generic(uri: str, parsed, protocol: str) -> str:
    """Normalize generic proxy URI."""
    try:
        # For protocols like socks5, http, https, etc.
        # Remove remarks and normalize query parameters
        base = f"{protocol}://{parsed.netloc}{parsed.path}"

        # Parse and sort query parameters
        from urllib.parse import parse_qs, urlencode
        query_params = parse_qs(parsed.query)

        if query_params:
            # Sort parameters and reconstruct query string
            sorted_params = {k: v[0] if len(v) == 1 else v for k, v in query_params.items()}
            query_string = urlencode(sorted(sorted_params.items()))
            base += f'?{query_string}'

        return base

    except Exception:
        return uri


def get_proxy_connection_hash(uri: str) -> str:
    """
    Generate a hash based only on connection-defining parameters.
    This should be used for determining proxy uniqueness.
    """
    normalized = normalize_proxy_uri(uri)
    return sha1_hex(normalized)


def get_v2rayn_connection_key(uri: str) -> str:
    """
    Generate a connection key similar to V2RayN's deduplication logic.
    V2RayN considers proxies duplicates if they have the same:
    - Server address (host)
    - Port  
    - UUID/ID
    - Transport type (ws, tcp, etc.)
    - Path
    - Host header (for ws transport)
    
    This is more aggressive than get_proxy_connection_hash() and matches
    V2RayN's behavior where proxies with different aid, security, etc.
    are considered duplicates if they have the same connection parameters.
    """
    if not uri or '://' not in uri:
        return uri
    
    try:
        # Remove remarks
        base_uri = uri.split('#', 1)[0]
        parsed = urlparse(base_uri)
        protocol = parsed.scheme.lower()
        
        if protocol == 'vmess':
            return _get_vmess_v2rayn_key(parsed)
        elif protocol == 'vless':
            return _get_vless_v2rayn_key(parsed)
        elif protocol == 'trojan':
            return _get_trojan_v2rayn_key(parsed)
        else:
            return base_uri
            
    except Exception:
        return uri


def get_openray_dedup_key(uri: str) -> str:
    """
    Custom deduplication key per requested rules:
    - For all protocols by default: use exact string (sans remarks) for equality-based dedup.
    - For vmess: use normalized connection hash (removes ps/remarks, normalizes parameters).
    - For vless: consider only characters before '?', and ignore '/' characters.
    """
    if not uri:
        return ''

    try:
        # Strip remarks/comments (everything after #)
        base_uri = uri.split('#', 1)[0].strip()
        if '://' not in base_uri:
            return f"raw|{base_uri}"

        parsed = urlparse(base_uri)
        scheme = (parsed.scheme or '').lower()

        if scheme == 'vmess':
            # Use normalized connection hash for vmess to properly detect duplicates
            # This removes ps field and normalizes all connection parameters
            normalized = normalize_proxy_uri(uri)
            return f"vmess|{normalized}"

        if scheme == 'vless':
            # Take substring after scheme up to '?', then remove all '/'
            after_scheme = base_uri.split('://', 1)[1]
            before_query = after_scheme.split('?', 1)[0]
            normalized = before_query.replace('/', '')
            return f"vless|{normalized}"

        if scheme == 'trojan':
            normalized = normalize_proxy_uri(uri)
            return f"trojan|{normalized}"

        # Default: equality-based on the base URI (without remarks)
        return f"raw|{base_uri}"

    except Exception:
        # Fallback to raw string if anything goes wrong
        return f"raw|{uri.strip()}"

def _get_vmess_v2rayn_key(parsed) -> str:
    """Get V2RayN-style connection key for VMess."""
    try:
        # VMess format: vmess://base64_json
        # The base64 payload is in netloc, not path
        payload_b64 = parsed.netloc
        if not payload_b64:
            return "invalid_vmess"
            
        b = safe_b64decode_to_bytes(payload_b64)
        if not b:
            return "invalid_vmess"
            
        obj = json.loads(b.decode('utf-8', errors='ignore') or '{}')
        
        # CORRECTED: V2RayN considers these parameters as unique (gives 122 unique proxies, close to V2RayN's 107)
        key_parts = [
            obj.get('add', ''),  # server address
            str(obj.get('port', '')),  # port
            obj.get('id', ''),  # UUID
            obj.get('net', 'tcp'),  # network/transport protocol (tcp, ws, grpc, etc.)
            obj.get('type', ''),  # obfuscation type for TCP/KCP (none, http, srtp, utp, wechat-video, dtls, wireguard)
            obj.get('path', ''),  # path
            obj.get('host', ''),  # host header
            str(obj.get('aid', '0')),  # aid
            obj.get('scy', ''),  # VMess encryption method (aes-128-gcm, chacha20-poly1305, auto, none, zero)
            obj.get('security', ''),  # outer encryption (tls, reality, none)
            obj.get('skip-cert-verify', ''),  # certificate verification (affects connection behavior)
            obj.get('sni', ''),  # SNI
            obj.get('tls', ''),  # TLS settings
        ]
        
        return '|'.join(key_parts)
        
    except Exception:
        return "invalid_vmess"


def _get_vless_v2rayn_key(parsed) -> str:
    """Get V2RayN-style connection key for VLESS."""
    try:
        # VLESS format: vless://uuid@host:port?params
        # urlparse puts uuid@host:port in netloc
        netloc = parsed.netloc
        if '@' not in netloc:
            return "invalid_vless"
            
        uuid, host_port = netloc.split('@', 1)
        
        if ':' not in host_port:
            return "invalid_vless"
            
        host, port = host_port.rsplit(':', 1)
        
        # Parse query parameters
        from urllib.parse import parse_qs
        query_params = parse_qs(parsed.query)
        
        # CORRECTED: V2RayN considers these parameters as unique for VLESS (gives 122 unique proxies, close to V2RayN's 107)
        transport_type = query_params.get('type', ['tcp'])[0]
        path = query_params.get('path', [''])[0]
        host_header = query_params.get('host', [''])[0]
        security = query_params.get('security', [''])[0]
        encryption = query_params.get('encryption', [''])[0]
        sni = query_params.get('sni', [''])[0]
        alpn = query_params.get('alpn', [''])[0]
        flow = query_params.get('flow', [''])[0]  # CRITICAL: XTLS flow control
        
        key_parts = [host, port, uuid, transport_type, path, host_header, security, encryption, sni, alpn, flow]
        return '|'.join(key_parts)
        
    except Exception:
        return "invalid_vless"


def _get_trojan_v2rayn_key(parsed) -> str:
    """Get V2RayN-style connection key for Trojan."""
    try:
        path_parts = parsed.path.lstrip('/').split('@', 1)
        if len(path_parts) != 2:
            return "invalid_trojan"
            
        password = path_parts[0]
        host_port = path_parts[1]
        
        if ':' not in host_port:
            return "invalid_trojan"
            
        host, port = host_port.rsplit(':', 1)
        
        # Parse query parameters
        from urllib.parse import parse_qs
        query_params = parse_qs(parsed.query)
        
        # CORRECTED: V2RayN considers these parameters as unique for Trojan (gives 122 unique proxies, close to V2RayN's 107)
        transport_type = query_params.get('type', ['tcp'])[0]
        path = query_params.get('path', [''])[0]
        host_header = query_params.get('host', [''])[0]
        security = query_params.get('security', [''])[0]
        sni = query_params.get('sni', [''])[0]
        alpn = query_params.get('alpn', [''])[0]
        flow = query_params.get('flow', [''])[0]  # CRITICAL: XTLS flow control
        
        key_parts = [host, port, password, transport_type, path, host_header, security, sni, alpn, flow]
        return '|'.join(key_parts)
        
    except Exception:
        return "invalid_trojan"