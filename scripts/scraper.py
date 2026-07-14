#!/usr/bin/env python3
"""
Główny skrypt trackera rejsów.

Uruchomienie:
    python3 scripts/scraper.py

Co robi:
  1. Scrapuje alerejsy.pl i rejsujznami.com dla skonfigurowanych kategorii/stref
     w zakresie dat z config.py (domyślnie 20-31 sierpnia 2026).
  2. Wczytuje poprzedni zapis (data/offers_latest.json), jeśli istnieje.
  3. Porównuje: nowe oferty, zniknięte oferty, zmiany cen -> data/changes_latest.json
  4. Zapisuje nowy stan do data/offers_latest.json + kopię z timestampem w data/history/.

Skrypt jest zaprojektowany żeby dało się go uruchamiać samemu (np. z crona / GitHub
Actions) i nie potrzebuje żadnego klucza API - tylko zwykłe requesty HTTP.
"""
import os
import sys
import json
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from parse_alerejsy import scrape_category
from parse_rejsujznami import scrape_zone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("scraper")


def load_previous():
    if os.path.exists(config.LATEST_FILE):
        with open(config.LATEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def offer_key(offer):
    """Unikalny klucz oferty - do porównywania między uruchomieniami."""
    return f"{offer['source']}|{offer['url']}"


def compute_changes(previous_offers, current_offers):
    prev_by_key = {offer_key(o): o for o in (previous_offers or [])}
    curr_by_key = {offer_key(o): o for o in current_offers}

    new_offers = [o for k, o in curr_by_key.items() if k not in prev_by_key]
    removed_offers = [o for k, o in prev_by_key.items() if k not in curr_by_key]

    price_changes = []
    for k, curr in curr_by_key.items():
        prev = prev_by_key.get(k)
        if not prev:
            continue
        prev_prices = prev.get("prices_eur", {})
        curr_prices = curr.get("prices_eur", {})
        diffs = {}
        for cabin_type in set(list(prev_prices.keys()) + list(curr_prices.keys())):
            old_p = prev_prices.get(cabin_type)
            new_p = curr_prices.get(cabin_type)
            if old_p is not None and new_p is not None and old_p != new_p:
                diffs[cabin_type] = {"old": old_p, "new": new_p, "delta": new_p - old_p}
        if diffs:
            price_changes.append({
                "source": curr["source"],
                "ship": curr["ship"],
                "start_date": curr["start_date"],
                "url": curr["url"],
                "changes": diffs,
            })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "new_offers": new_offers,
        "removed_offers": removed_offers,
        "price_changes": price_changes,
    }


def run():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.HISTORY_DIR, exist_ok=True)

    all_offers = []

    for key, url in config.ALEREJSY_CATEGORIES.items():
        log.info("Scrapuję alerejsy.pl / %s ...", key)
        try:
            offers = scrape_category(key, url, config.TARGET_START, config.TARGET_END)
            log.info("  -> znaleziono %d ofert w zakresie dat", len(offers))
            all_offers.extend(offers)
        except Exception:
            log.exception("Błąd przy scrapowaniu alerejsy.pl / %s", key)

    for key, url in config.REJSUJZNAMI_ZONES.items():
        log.info("Scrapuję rejsujznami.com / %s ...", key)
        try:
            offers = scrape_zone(key, url, config.TARGET_START, config.TARGET_END)
            log.info("  -> znaleziono %d ofert w zakresie dat", len(offers))
            all_offers.extend(offers)
        except Exception:
            log.exception("Błąd przy scrapowaniu rejsujznami.com / %s", key)

    previous = load_previous()
    changes = compute_changes(previous, all_offers)

    log.info(
        "Podsumowanie: %d nowych, %d zniknionych, %d ze zmianą ceny",
        len(changes["new_offers"]), len(changes["removed_offers"]), len(changes["price_changes"]),
    )

    with open(config.CHANGES_FILE, "w", encoding="utf-8") as f:
        json.dump(changes, f, ensure_ascii=False, indent=2)

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_start": config.TARGET_START.isoformat(),
        "target_end": config.TARGET_END.isoformat(),
        "offer_count": len(all_offers),
        "offers": all_offers,
    }

    with open(config.LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with open(f"{config.HISTORY_DIR}/offers_{ts}.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    log.info("Zapisano %s ofert do %s", len(all_offers), config.LATEST_FILE)


if __name__ == "__main__":
    run()
