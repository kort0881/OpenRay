from __future__ import annotations
import os
import base64
import hashlib
import threading

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
        payload_b64 = parsed.path.lstrip('/')
        if not payload_b64:
            return uri

        b = safe_b64decode_to_bytes(payload_b64)
        if not b:
            return uri

        import json
        obj = json.loads(b.decode('utf-8', errors='ignore') or '{}')

        # Extract connection-defining parameters only
        normalized = {
            'v': obj.get('v', '2'),
            'ps': '',  # Remove remarks
            'add': obj.get('add', obj.get('address', '')),
            'port': obj.get('port', obj.get('portNumber', '')),
            'id': obj.get('id', ''),
            'aid': obj.get('aid', '0'),
            'scy': obj.get('scy', 'auto'),
            'net': obj.get('net', 'tcp'),
            'type': obj.get('type', 'none'),
            'host': obj.get('host', ''),
            'path': obj.get('path', ''),
            'tls': obj.get('tls', ''),
            'sni': obj.get('sni', ''),
            'alpn': obj.get('alpn', ''),
            'fp': obj.get('fp', ''),
        }

        # Remove empty values and normalize
        normalized = {k: v for k, v in normalized.items() if v}

        # Normalize defaults
        if normalized.get('aid') == '0':
            normalized['aid'] = '0'
        if normalized.get('scy') == 'auto':
            normalized['scy'] = 'auto'
        if normalized.get('net') == 'tcp':
            normalized['net'] = 'tcp'
        if normalized.get('type') == 'none':
            normalized['type'] = 'none'

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
        # Trojan format: trojan://password@host:port?params
        path_parts = parsed.path.lstrip('/').split('@', 1)
        if len(path_parts) != 2:
            return uri

        password = path_parts[0]
        host_port = path_parts[1]

        # Parse query parameters
        from urllib.parse import parse_qs
        query_params = parse_qs(parsed.query)

        # Extract connection-defining parameters
        normalized_params = {}

        # Required parameters
        if password:
            normalized_params['password'] = password
        if ':' in host_port:
            host, port = host_port.rsplit(':', 1)
            normalized_params['host'] = host
            normalized_params['port'] = port

        # Connection-defining query parameters
        connection_params = [
            'security', 'type', 'path', 'host', 'sni', 'alpn', 'fp', 'pbk', 'sid', 'flow'
        ]

        for param in connection_params:
            if param in query_params and query_params[param]:
                value = query_params[param][0]
                if value:  # Only include non-empty values
                    normalized_params[param] = value

        # Normalize defaults
        if normalized_params.get('security') == 'tls':
            normalized_params['security'] = 'tls'

        # Reconstruct URI
        query_string = '&'.join(f'{k}={v}' for k, v in sorted(normalized_params.items()) if k not in ['host', 'port', 'password'])
        host_port_part = f"{normalized_params.get('host', '')}:{normalized_params.get('port', '')}"
        password_part = normalized_params.get('password', '')

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