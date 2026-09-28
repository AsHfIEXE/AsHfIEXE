"""Generate a self-hosted SVG chart from GitHub's contribution calendar."""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USERNAME = os.environ.get("GITHUB_USERNAME", "ashfiexe")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
OUTPUT = Path(__file__).resolve().parents[2] / "assets" / "activity-graph.svg"

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_calendar() -> tuple[int, list[tuple[dt.date, int]]]:
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required to query the GitHub GraphQL API")

    today = dt.date.today()
    first_day = today - dt.timedelta(days=364)
    body = json.dumps(
        {
            "query": QUERY,
            "variables": {
                "login": USERNAME,
                "from": f"{first_day.isoformat()}T00:00:00Z",
                "to": f"{today.isoformat()}T23:59:59Z",
            },
        }
    ).encode()
    request = Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "ashfiexe-profile-activity-graph",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError) as error:
        raise RuntimeError(f"GitHub GraphQL request failed: {error}") from error

    if payload.get("errors"):
        messages = "; ".join(error.get("message", "unknown GraphQL error") for error in payload["errors"])
        raise RuntimeError(f"GitHub GraphQL returned an error: {messages}")

    user = payload.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {USERNAME}")

    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [
        (dt.date.fromisoformat(day["date"]), int(day["contributionCount"]))
        for week in calendar["weeks"]
        for day in week["contributionDays"]
    ]
    days = [(date, count) for date, count in days if date <= today][-365:]
    return int(calendar["totalContributions"]), days


def render_svg(total: int, days: list[tuple[dt.date, int]]) -> str:
    width, height = 960, 300
    left, right, top, bottom = 62, 28, 58, 44
    plot_width = width - left - right
    plot_height = height - top - bottom
    maximum = max((count for _, count in days), default=0)
    scale_max = max(1, math.ceil(maximum / 5) * 5)

    def x_at(index: int) -> float:
        return left + plot_width * index / max(1, len(days) - 1)

    def y_at(count: int) -> float:
        return top + plot_height * (1 - count / scale_max)

    coords = [(x_at(i), y_at(count)) for i, (_, count) in enumerate(days)]
    baseline = top + plot_height
    line_path = " ".join(
        f"{'M' if i == 0 else 'L'} {x:.2f} {y:.2f}" for i, (x, y) in enumerate(coords)
    )
    area_path = f"{line_path} L {coords[-1][0]:.2f} {baseline:.2f} L {coords[0][0]:.2f} {baseline:.2f} Z" if coords else ""

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        '<title id="title">GitHub activity · past year</title>',
        f'<desc id="description">{total} contributions in the last year, plotted by day.</desc>',
        "<defs>",
        '<linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#00DBAF" stop-opacity="0.30"/><stop offset="100%" stop-color="#00DBAF" stop-opacity="0.01"/></linearGradient>',
        "</defs>",
        '<rect width="100%" height="100%" rx="14" fill="#0D1519"/>',
        '<rect x="0.5" y="0.5" width="959" height="299" rx="13.5" fill="none" stroke="#20343A"/>',
        '<text x="30" y="32" fill="#00DBAF" font-family="Segoe UI,Arial,sans-serif" font-size="15" font-weight="600">GITHUB ACTIVITY · PAST YEAR</text>',
        f'<text x="930" y="32" text-anchor="end" fill="#C9D4D0" font-family="Segoe UI,Arial,sans-serif" font-size="13">{total:,} contributions</text>',
    ]

    for tick in range(4):
        value = round(scale_max * tick / 3)
        y = y_at(value)
        parts.extend(
            [
                f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#20343A" stroke-width="1"/>',
                f'<text x="{left - 12}" y="{y + 4:.2f}" text-anchor="end" fill="#80918F" font-family="Segoe UI,Arial,sans-serif" font-size="11">{value}</text>',
            ]
        )

    month_seen: set[tuple[int, int]] = set()
    for index, (date, _) in enumerate(days):
        key = (date.year, date.month)
        if date.day == 1 or index == 0:
            if key not in month_seen:
                parts.append(
                    f'<text x="{x_at(index):.2f}" y="{height - 14}" fill="#A9B8B7" font-family="Segoe UI,Arial,sans-serif" font-size="11">{html.escape(date.strftime("%b"))}</text>'
                )
                month_seen.add(key)

    if area_path:
        parts.append(f'<path d="{area_path}" fill="url(#area)"/>')
        parts.append(f'<path d="{line_path}" fill="none" stroke="#00DBAF" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>')
        for (date, count), (x, y) in zip(days, coords):
            if count:
                label = html.escape(f"{date.isoformat()}: {count} contributions")
                parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.5" fill="#FFB86B"><title>{label}</title></circle>')

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    total, days = fetch_calendar()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_svg(total, days), encoding="utf-8")


if __name__ == "__main__":
    main()
