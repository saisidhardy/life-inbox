"""Rate limiting and daily usage cap helpers for /api/analyze."""

import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, Request, status


def get_rate_limit_per_minute() -> Optional[int]:
    """Get per-minute rate limit from env var, or None if unconfigured."""
    raw = os.getenv("ANALYZE_RATE_LIMIT_PER_MINUTE", "").strip()
    if not raw:
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except ValueError:
        return None


def get_daily_cap() -> Optional[int]:
    """Get daily cap from env var, or None if unconfigured."""
    raw = os.getenv("ANALYZE_DAILY_CAP", "").strip()
    if not raw:
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except ValueError:
        return None


class AnalyzeRateLimiter:
    """Thread-safe rate limiter with sliding-window minute limits and a daily cap."""

    def __init__(self):
        self._lock = threading.Lock()
        # client_ip -> list of epoch timestamps in the last 60 seconds
        self._minute_buckets: Dict[str, List[float]] = defaultdict(list)
        # current_utc_day -> total daily count
        self._daily_counts: Dict[str, int] = defaultdict(int)

    def reset(self) -> None:
        """Clear all rate limiting state (useful in test suites)."""
        with self._lock:
            self._minute_buckets.clear()
            self._daily_counts.clear()

    def get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
            if client_ip:
                return client_ip
        if request.client and request.client.host:
            return request.client.host
        return "unknown_client"

    def check_and_record(self, request: Request) -> Tuple[bool, str, int]:
        """Check rate limits. Returns (allowed, error_message, retry_after_seconds)."""
        minute_limit = get_rate_limit_per_minute()
        daily_cap = get_daily_cap()

        # If neither rate limit is configured, allow request immediately
        if minute_limit is None and daily_cap is None:
            return True, "", 0

        client_ip = self.get_client_ip(request)
        now = time.time()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._lock:
            # 1. Check daily cap if configured
            if daily_cap is not None:
                current_day_count = self._daily_counts[today]
                if current_day_count >= daily_cap:
                    midnight_ts = (
                        datetime.now(timezone.utc)
                        .replace(hour=23, minute=59, second=59, microsecond=999999)
                        .timestamp()
                    )
                    retry_after = max(1, int(midnight_ts - now))
                    return (
                        False,
                        f"Daily analysis cap reached ({daily_cap} requests/day). Limit resets at midnight UTC.",
                        retry_after,
                    )

            # 2. Check minute sliding window if configured
            if minute_limit is not None:
                timestamps = self._minute_buckets[client_ip]
                cutoff = now - 60.0
                valid_timestamps = [t for t in timestamps if t > cutoff]
                self._minute_buckets[client_ip] = valid_timestamps

                if len(valid_timestamps) >= minute_limit:
                    oldest = valid_timestamps[0]
                    retry_after = max(1, int(60.0 - (now - oldest)))
                    return (
                        False,
                        f"Rate limit exceeded. Maximum {minute_limit} analysis requests per minute.",
                        retry_after,
                    )

            # Record this request
            self._minute_buckets[client_ip].append(now)
            self._daily_counts[today] += 1
            return True, "", 0


analyze_rate_limiter = AnalyzeRateLimiter()


def enforce_analyze_rate_limit(request: Request) -> None:
    """FastAPI dependency or helper to enforce rate limiting on /api/analyze."""
    allowed, message, retry_after = analyze_rate_limiter.check_and_record(request)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=message,
            headers={"Retry-After": str(retry_after)},
        )
