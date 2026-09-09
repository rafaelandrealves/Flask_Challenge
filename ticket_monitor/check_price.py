"""
Scrapes the viagogo event page for Sporting CP vs Manchester United and
extracts the cheapest listed ticket price. Runs on a GitHub Actions
schedule (see .github/workflows/price-monitor.yml) so it executes with
normal outbound internet access.

Writes ticket_monitor/latest_price.json with the result so a separate
process (a Claude Code Routine) can read it and decide whether to notify.
"""
import json
import re
import sys
from datetime import datetime, timezone

import requests

EVENT_URL = "https://www.viagogo.com/Sports-Tickets/Soccer/Sporting-CP-Tickets/E-161831095"
OUTPUT_PATH = "ticket_monitor/latest_price.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}


def extract_from_jsonld(html):
    """Look for schema.org Event/Offer structured data with a price."""
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            offers = item.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if isinstance(offers, list):
                for offer in offers:
                    if not isinstance(offer, dict):
                        continue
                    price = offer.get("lowPrice") or offer.get("price")
                    currency = offer.get("priceCurrency")
                    if price is not None:
                        try:
                            return float(price), currency
                        except (TypeError, ValueError):
                            pass
    return None, None


def extract_from_meta(html):
    """Look for og:description / twitter meta tags that often say 'From €NN'."""
    for match in re.finditer(
        r'<meta[^>]+(?:property|name)=["\'](?:og:description|twitter:data1|description)["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    ):
        content = match.group(1)
        price_match = re.search(r"([€$£])\s?(\d[\d,.]*)", content)
        if price_match:
            symbol, amount = price_match.groups()
            try:
                return float(amount.replace(",", "")), CURRENCY_SYMBOLS.get(symbol)
            except ValueError:
                pass
    return None, None


def extract_from_body_regex(html):
    """Last-resort heuristic: smallest currency amount near the word 'from'."""
    amounts = []
    for match in re.finditer(
        r"from[^€$£\d]{0,20}([€$£])\s?(\d[\d,.]*)", html, re.IGNORECASE
    ):
        symbol, amount = match.groups()
        try:
            amounts.append((float(amount.replace(",", "")), CURRENCY_SYMBOLS.get(symbol)))
        except ValueError:
            continue
    if amounts:
        amounts.sort(key=lambda x: x[0])
        return amounts[0]
    return None, None


def main():
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "event_url": EVENT_URL,
        "price": None,
        "currency": None,
        "status": None,
        "http_status": None,
    }

    try:
        resp = requests.get(EVENT_URL, headers=HEADERS, timeout=30)
    except requests.RequestException as exc:
        result["status"] = f"request_error: {exc}"
        write_result(result)
        sys.exit(0)

    result["http_status"] = resp.status_code
    html = resp.text

    print(f"HTTP status: {resp.status_code}")
    print(f"Response length: {len(html)} chars")
    print("First 1500 chars of response:\n" + html[:1500])

    if resp.status_code != 200:
        result["status"] = "http_error"
        write_result(result)
        return

    for extractor in (extract_from_jsonld, extract_from_meta, extract_from_body_regex):
        price, currency = extractor(html)
        if price is not None:
            result["price"] = price
            result["currency"] = currency or "EUR"
            result["status"] = f"ok ({extractor.__name__})"
            break
    else:
        result["status"] = "parse_failed"

    write_result(result)


def write_result(result):
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print("Wrote result:", json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
