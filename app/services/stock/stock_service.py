"""
Stock footage service — search & download from public stock libraries.

Currently supports:
  - Pexels  (https://www.pexels.com/api/documentation/)
  - Pixabay (https://pixabay.com/api/docs/)

Each provider returns video URLs which are downloaded to a target directory
so the existing mix pipeline can treat them as just-another scene folder.

Used by: app/worker.py :: POST /smart-pad
"""

import os
import time
import logging
import urllib.parse
from typing import List, Optional

import requests

logger = logging.getLogger("shadowblade.stock")

PEXELS_API = "https://api.pexels.com/videos/search"
PIXABAY_API = "https://pixabay.com/api/videos/"

REQUEST_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120
MAX_PER_KEYWORD = 8


class StockProviderError(Exception):
    pass


# ---------------------------------------------------------------------------
# Pexels
# ---------------------------------------------------------------------------

def _pexels_search(keyword: str, api_key: str, per_page: int = MAX_PER_KEYWORD,
                   orientation: str = "portrait") -> List[dict]:
    """Return list of {url, duration, width, height} for keyword."""
    headers = {"Authorization": api_key}
    params = {
        "query": keyword,
        "per_page": per_page,
        "orientation": orientation,
    }
    r = requests.get(PEXELS_API, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    if r.status_code == 401:
        raise StockProviderError("Pexels: invalid API key")
    if r.status_code != 200:
        raise StockProviderError(f"Pexels HTTP {r.status_code}: {r.text[:200]}")

    out = []
    for v in r.json().get("videos", []):
        # pick a sd-ish file: prefer the largest <= 1920 px
        files = sorted(
            (f for f in v.get("video_files", []) if f.get("link")),
            key=lambda f: -(f.get("width") or 0),
        )
        chosen = None
        for f in files:
            w = f.get("width") or 0
            if 720 <= w <= 1920:
                chosen = f
                break
        if not chosen and files:
            chosen = files[0]
        if not chosen:
            continue

        out.append({
            "url": chosen["link"],
            "duration": v.get("duration") or 0,
            "width": chosen.get("width") or 0,
            "height": chosen.get("height") or 0,
            "id": v.get("id"),
            "ext": "mp4",
        })
    return out


# ---------------------------------------------------------------------------
# Pixabay
# ---------------------------------------------------------------------------

def _pixabay_search(keyword: str, api_key: str, per_page: int = MAX_PER_KEYWORD) -> List[dict]:
    params = {
        "key": api_key,
        "q": keyword,
        "per_page": per_page,
        "video_type": "all",
    }
    r = requests.get(PIXABAY_API, params=params, timeout=REQUEST_TIMEOUT)
    if r.status_code == 400:
        raise StockProviderError(f"Pixabay: bad request — likely invalid key. {r.text[:200]}")
    if r.status_code != 200:
        raise StockProviderError(f"Pixabay HTTP {r.status_code}: {r.text[:200]}")

    out = []
    for v in r.json().get("hits", []):
        videos = v.get("videos") or {}
        # Pixabay returns sizes large/medium/small/tiny — prefer medium for size/quality balance
        chosen = None
        for size in ("medium", "large", "small", "tiny"):
            f = videos.get(size)
            if f and f.get("url"):
                chosen = f
                break
        if not chosen:
            continue
        out.append({
            "url": chosen["url"],
            "duration": v.get("duration") or 0,
            "width": chosen.get("width") or 0,
            "height": chosen.get("height") or 0,
            "id": v.get("id"),
            "ext": "mp4",
        })
    return out


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download(url: str, dest_path: str) -> bool:
    try:
        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
        if os.path.getsize(dest_path) < 50_000:
            os.remove(dest_path)
            return False
        return True
    except Exception as e:
        logger.warning(f"download failed {url[:80]}…: {e}")
        if os.path.exists(dest_path):
            try: os.remove(dest_path)
            except OSError: pass
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_stock_footage(
    keywords: List[str],
    target_seconds: float,
    out_dir: str,
    provider: str = "pexels",
    api_key: Optional[str] = None,
    orientation: str = "portrait",
    per_keyword: int = MAX_PER_KEYWORD,
) -> dict:
    """
    Search & download stock videos for the given keywords until we collect
    >= target_seconds of footage in `out_dir`.

    Returns: { downloaded: N, total_duration: secs, files: [...], skipped_reasons: [...] }
    """
    if not api_key:
        raise StockProviderError(f"{provider} api_key not configured in config.yml -> resource.{provider}.api_key")
    if not keywords:
        raise StockProviderError("no keywords provided")

    os.makedirs(out_dir, exist_ok=True)

    collected = []
    total_dur = 0.0
    seen_ids = set()
    skipped = []

    for kw in keywords:
        if total_dur >= target_seconds:
            break
        kw = kw.strip()
        if not kw:
            continue
        try:
            if provider == "pexels":
                hits = _pexels_search(kw, api_key, per_page=per_keyword, orientation=orientation)
            elif provider == "pixabay":
                hits = _pixabay_search(kw, api_key, per_page=per_keyword)
            else:
                raise StockProviderError(f"unknown provider: {provider}")
        except StockProviderError as e:
            skipped.append(f"{kw}: {e}")
            continue

        logger.info(f"[stock:{provider}] kw='{kw}' got {len(hits)} hits")

        for h in hits:
            if total_dur >= target_seconds:
                break
            hid = h.get("id")
            if hid and hid in seen_ids:
                continue
            seen_ids.add(hid)

            safe_kw = "".join(c if c.isalnum() else "_" for c in kw)[:20]
            fname = f"{provider}-{safe_kw}-{hid or int(time.time()*1000)}.{h['ext']}"
            dest = os.path.join(out_dir, fname)
            if _download(h["url"], dest):
                collected.append(dest)
                total_dur += h.get("duration") or 0
                logger.info(f"  ↓ {os.path.basename(dest)}  +{h.get('duration')}s  total={total_dur:.0f}s")
            else:
                skipped.append(f"download failed: {h['url'][:60]}")

    return {
        "downloaded": len(collected),
        "total_duration": total_dur,
        "files": collected,
        "skipped_reasons": skipped,
        "out_dir": out_dir,
    }
