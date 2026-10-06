"""Worker de áudio — download com streaming (FASE 3B).

Sem carregar arquivos grandes na RAM; timeouts e teto de tamanho
configuráveis; proteção SSRF básica (só http/https, sem localhost ou
IPs privados — inclui link-local de metadados de nuvem).
"""

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class DownloadError(Exception):
    """Falha de download com categoria segura (sem URL/segredo)."""


def validate_source_url(url: str) -> str:
    """Valida esquema + destino (anti-SSRF). Retorna a URL íntegra."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise DownloadError("URL inválida.")
    try:
        parts = urlparse(url)
    except ValueError:
        raise DownloadError("URL inválida.")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise DownloadError("URL inválida.")
    host = parts.hostname
    if host in ("localhost",):
        raise DownloadError("Destino não permitido.")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise DownloadError("Destino não permitido.")
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            raise DownloadError("Destino não permitido.")
        if any(ip in net for net in _BLOCKED_NETWORKS):
            raise DownloadError("Destino não permitido.")
    return url


def download_audio(url: str, destination: Path, max_bytes: int,
                   timeout_s: float = 30.0,
                   client: httpx.Client | None = None) -> dict:
    """Baixa por streaming para `destination`. Retorna metadados.

    `client` opcional existe para testes (MockTransport); em produção
    é sempre um cliente real. Nunca carrega o arquivo inteiro na RAM.
    """
    validate_source_url(url)
    if max_bytes <= 0:
        raise DownloadError("Limite de tamanho inválido.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=timeout_s,
                                  write=timeout_s, pool=10.0),
            follow_redirects=False,
        )
    try:
        try:
            with client.stream("GET", url) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    raise DownloadError("Redirecionamento não permitido.")
                if resp.status_code == 404:
                    raise DownloadError("Áudio não encontrado.")
                if 400 <= resp.status_code < 500:
                    raise DownloadError("Falha ao baixar áudio.")
                if resp.status_code >= 500:
                    raise DownloadError("Origem indisponível.")
                if resp.status_code != 200:
                    raise DownloadError("Falha ao baixar áudio.")
                declared = resp.headers.get("content-length")
                if declared is not None:
                    try:
                        if int(declared) > max_bytes:
                            raise DownloadError("Arquivo muito grande.")
                    except (TypeError, ValueError):
                        raise DownloadError("Arquivo muito grande.")
                total = 0
                with open(destination, "wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        total += len(chunk)
                        if total > max_bytes:
                            raise DownloadError("Arquivo muito grande.")
                        fh.write(chunk)
                return {
                    "path": str(destination),
                    "bytes": total,
                    "content_type": resp.headers.get("content-type"),
                }
        except DownloadError:
            raise
        except (httpx.TimeoutException, httpx.ConnectError,
                httpx.NetworkError) as exc:
            raise DownloadError(type(exc).__name__)
    finally:
        if own_client:
            client.close()
