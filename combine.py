#!/usr/bin/env python3
"""Combine Turkish and Russian IPTV playlists for IBO Player."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
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
TIMEOUT_SECONDS = 30


def download_playlist(name: str, url: str) -> str | None:
    """Download a playlist and return its text, or None if it fails."""
    logging.info("Downloading %s playlist from %s", name, url)
    request = Request(
        url,
        headers={"User-Agent": "ibo-iptv-playlist-combiner/1.0"},
    )

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            encoding = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(encoding, errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logging.warning("Could not download %s playlist: %s", name, exc)
        return None


def iter_channels(playlist_text: str) -> Iterable[tuple[str, str]]:
    """Yield (#EXTINF line, stream URL) pairs from an M3U playlist."""
    pending_extinf: str | None = None

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

        yield pending_extinf, line
        pending_extinf = None


def build_combined_playlist() -> list[str]:
    lines = ["#EXTM3U"]
    seen_urls: set[str] = set()

    for name, url, section_comment in PLAYLISTS:
        playlist_text = download_playlist(name, url)
        added_count = 0
        skipped_duplicates = 0

        lines.append(section_comment)

        if playlist_text is None:
            logging.info("Added 0 %s channels because the source failed", name)
            continue

        for extinf_line, stream_url in iter_channels(playlist_text):
            if stream_url in seen_urls:
                skipped_duplicates += 1
                continue

            seen_urls.add(stream_url)
            lines.append(extinf_line)
            lines.append(stream_url)
            added_count += 1

        logging.info(
            "Added %s %s channels (%s duplicate stream URLs skipped)",
            added_count,
            name,
            skipped_duplicates,
        )

    logging.info("Total channels added: %s", len(seen_urls))
    return lines


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    combined_lines = build_combined_playlist()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text("\n".join(combined_lines) + "\n", encoding="utf-8")
    logging.info("Wrote %s", OUTPUT_FILE)


if __name__ == "__main__":
    main()
