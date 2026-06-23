#!/usr/bin/env python3
"""Combine fast, working public Turkish and Russian IPTV channels for IBO Player."""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote_plus
from urllib.request import Request, urlopen


PLAYLISTS = [
    (
        "Turkish",
        "https://iptv-org.github.io/iptv/languages/tur.m3u",
        "# Turkish Channels",
    ),
    (
        "Russian",
        "https://iptv-org.github.io/iptv/countries/ru.m3u",
        "# Russian Channels",
    ),
]

OUTPUT_FILE = Path("docs") / "combined.m3u"
DOWNLOAD_TIMEOUT_SECONDS = float(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "30"))
STREAM_TIMEOUT_SECONDS = float(os.getenv("STREAM_TIMEOUT_SECONDS", "3"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "64"))
PROBE_STREAMS = os.getenv("PROBE_STREAMS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
DEFAULT_USER_AGENT = "ibo-iptv-playlist-combiner/1.0"
ATTRIBUTE_RE = re.compile(r'([\w-]+)="([^"]*)"')


@dataclass(frozen=True)
class Channel:
    extinf: str
    stream_url: str
    request_url: str
    headers: tuple[tuple[str, str], ...]
    source: str
    index: int


@dataclass(frozen=True)
class ProbeResult:
    channel: Channel
    ok: bool
    latency_seconds: float | None
    reason: str | None = None


def download_playlist(name: str, url: str) -> str | None:
    """Download a playlist and return its text, or None if it fails."""
    logging.info("Downloading %s playlist from %s", name, url)
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})

    try:
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            encoding = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(encoding, errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logging.warning("Could not download %s playlist: %s", name, exc)
        return None


def parse_extinf_headers(extinf: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    attrs = {key.lower(): value for key, value in ATTRIBUTE_RE.findall(extinf)}

    user_agent = attrs.get("http-user-agent") or attrs.get("user-agent")
    if user_agent:
        headers["User-Agent"] = user_agent

    referer = attrs.get("http-referrer") or attrs.get("referrer")
    if referer:
        headers["Referer"] = referer

    return headers


def parse_pipe_options(stream_url: str) -> tuple[str, dict[str, str]]:
    if "|" not in stream_url:
        return stream_url, {}

    request_url, raw_options = stream_url.split("|", 1)
    headers: dict[str, str] = {}

    for option in raw_options.split("&"):
        if "=" not in option:
            continue
        key, value = option.split("=", 1)
        normalized_key = key.strip().lower()
        decoded_value = unquote_plus(value.strip())

        if normalized_key in {"user-agent", "useragent", "http-user-agent"}:
            headers["User-Agent"] = decoded_value
        elif normalized_key in {"referer", "referrer", "http-referrer"}:
            headers["Referer"] = decoded_value

    return request_url.strip(), headers


def iter_channels(name: str, playlist_text: str) -> Iterable[Channel]:
    """Yield parsed channel objects from an M3U playlist."""
    pending_extinf: str | None = None
    channel_index = 0

    for raw_line in playlist_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF"):
            pending_extinf = line
            continue

        if line.startswith("#"):
            continue

        if pending_extinf is None:
            continue

        request_url, pipe_headers = parse_pipe_options(line)
        if not request_url.lower().startswith(("http://", "https://")):
            pending_extinf = None
            continue

        headers = {"User-Agent": DEFAULT_USER_AGENT}
        headers.update(parse_extinf_headers(pending_extinf))
        headers.update(pipe_headers)

        yield Channel(
            extinf=pending_extinf,
            stream_url=line,
            request_url=request_url,
            headers=tuple(headers.items()),
            source=name,
            index=channel_index,
        )

        channel_index += 1
        pending_extinf = None


def probe_channel(channel: Channel) -> ProbeResult:
    headers = dict(channel.headers)
    headers.setdefault("User-Agent", DEFAULT_USER_AGENT)
    headers.setdefault("Accept", "*/*")
    headers.setdefault("Range", "bytes=0-1023")

    request = Request(channel.request_url, headers=headers, method="GET")
    start = time.perf_counter()

    try:
        with urlopen(request, timeout=STREAM_TIMEOUT_SECONDS) as response:
            response.read(1024)
            latency = time.perf_counter() - start
            if 200 <= response.status < 400:
                return ProbeResult(channel, True, latency)
            return ProbeResult(channel, False, latency, f"HTTP {response.status}")
    except HTTPError as exc:
        latency = time.perf_counter() - start
        return ProbeResult(channel, False, latency, f"HTTP {exc.code}")
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        latency = time.perf_counter() - start
        return ProbeResult(channel, False, latency, exc.__class__.__name__)


def filter_working_channels(channels: list[Channel], source_name: str) -> list[Channel]:
    if not PROBE_STREAMS:
        logging.info("Stream probing disabled; keeping %s %s channels", len(channels), source_name)
        return channels

    if not channels:
        return []

    logging.info(
        "Testing %s %s stream URLs with %.1fs timeout",
        len(channels),
        source_name,
        STREAM_TIMEOUT_SECONDS,
    )
    results: list[ProbeResult] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_channel = {executor.submit(probe_channel, channel): channel for channel in channels}
        for future in as_completed(future_to_channel):
            channel = future_to_channel[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - a bad stream must never stop the build
                results.append(ProbeResult(channel, False, None, exc.__class__.__name__))

    working_results = [result for result in results if result.ok]
    working_by_url = {result.channel.stream_url: result for result in working_results}
    working_channels = [channel for channel in channels if channel.stream_url in working_by_url]
    failed_count = len(channels) - len(working_channels)

    if working_results:
        fastest = min(result.latency_seconds or 0 for result in working_results)
        slowest = max(result.latency_seconds or 0 for result in working_results)
        logging.info(
            "%s responsive %s channels kept; %s broken/slow channels removed "
            "(fastest %.2fs, slowest %.2fs)",
            len(working_channels),
            source_name,
            failed_count,
            fastest,
            slowest,
        )
    else:
        logging.warning("No responsive %s channels found; removed %s candidates", source_name, failed_count)

    return working_channels


def build_combined_playlist() -> list[str]:
    lines = ["#EXTM3U"]
    seen_request_urls: set[str] = set()
    total_added = 0

    for name, url, section_comment in PLAYLISTS:
        playlist_text = download_playlist(name, url)
        lines.append(section_comment)

        if playlist_text is None:
            logging.info("Added 0 %s channels because the source failed", name)
            continue

        candidates: list[Channel] = []
        skipped_duplicates = 0

        for channel in iter_channels(name, playlist_text):
            if channel.request_url in seen_request_urls:
                skipped_duplicates += 1
                continue
            seen_request_urls.add(channel.request_url)
            candidates.append(channel)

        working_channels = filter_working_channels(candidates, name)

        for channel in working_channels:
            lines.append(channel.extinf)
            lines.append(channel.stream_url)

        total_added += len(working_channels)
        logging.info(
            "Added %s %s channels (%s duplicate stream URLs skipped)",
            len(working_channels),
            name,
            skipped_duplicates,
        )

    logging.info("Total working channels added: %s", total_added)
    return lines


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    combined_lines = build_combined_playlist()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text("\n".join(combined_lines) + "\n", encoding="utf-8", newline="\n")
    logging.info("Wrote %s", OUTPUT_FILE)


if __name__ == "__main__":
    main()
