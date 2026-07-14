"""
Parser dla rejsujznami.com

Podobna strategia jak w parse_alerejsy.py: kotwiczymy się na widocznym tekście
i wzorcach linków, bo to najbardziej odporne na zmiany w markupie.

Charakterystyczne cechy tej strony:
  - link do oferty zawiera "/i_<liczba>/" na końcu
  - blok oferty zawiera "z:<dzień tygodnia> D Miesiąc RRRR" i "do:<...>"
  - ceny podpisane jako "WEWNĘTRZNA:", "Z OKNEM:", "Z BALKONEM:", "TYPU SUITE:"
  - strona jest posortowana rosnąco po dacie wypłynięcia i ma paginację /g_N/
"""
import re
import time
import logging
from datetime import date, datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY, MAX_PAGES

log = logging.getLogger("rejsujznami")

DETAIL_LINK_RE = re.compile(r"/i_\d+/?$")

MONTHS_PL = {
    "stycznia": 1, "styczen": 1, "lutego": 2, "luty": 2, "marca": 3, "marzec": 3,
    "kwietnia": 4, "kwiecien": 4, "maja": 5, "maj": 5, "czerwca": 6, "czerwiec": 6,
    "lipca": 7, "lipiec": 7, "sierpnia": 8, "sierpien": 8, "wrzesnia": 9, "wrzesien": 9,
    "pazdziernika": 10, "pazdziernik": 10, "listopada": 11, "listopad": 11,
    "grudnia": 12, "grudzien": 12,
}


def _strip_pl(s):
    repl = str.maketrans("ąćęłńóśźż", "acelnoszz")
    return s.lower().translate(repl)


DATE_LINE_RE = re.compile(
    r"(?:z|do):\s*\w+\s+(\d{1,2})\s+(\w+)\s+(\d{4})", re.IGNORECASE
)

PRICE_LINE_RE = re.compile(
    r"(WEWN[ĘE]TRZNA|Z OKNEM|Z BALKONEM|TYPU SUITE):\s*([\d.,\s]+|n\.d\.|brak)",
    re.IGNORECASE,
)


def _parse_pl_date(day, month_word, year):
    month = MONTHS_PL.get(_strip_pl(month_word))
    if not month:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def _parse_price(raw):
    raw = raw.strip()
    if not raw or "n.d" in raw.lower() or "brak" in raw.lower():
        return None
    cleaned = raw.replace("\xa0", "").replace(" ", "").replace(".", "").replace(",00", "")
    m = re.search(r"(\d+)", cleaned)
    return int(m.group(1)) if m else None


def _find_offer_container(a_tag):
    node = a_tag
    for _ in range(8):
        if node is None:
            break
        text = node.get_text("\n")
        if "Liczba nocy" in text and re.search(r"\bz:", text):
            return node
        node = node.parent
    return None


def _extract_ship_name(container):
    for a in container.find_all("a"):
        text = a.get_text(strip=True)
        if text and text.isupper() and len(text) > 3:
            return text
    return None


def _overlaps(start_d, end_d, target_start, target_end):
    return start_d <= target_end and end_d >= target_start


def scrape_zone(zone_key, base_url, target_start, target_end, session=None):
    """Scrapuje jedną strefę (paginacja /g_N/) i zwraca listę ofert.
    Zatrzymuje się wcześniej, jeśli oferty na stronie są już wyraźnie później
    niż target_end (strona jest posortowana rosnąco po dacie)."""
    session = session or requests.Session()
    offers = []
    seen_links = set()
    base_url = base_url.rstrip("/") + "/"

    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}g_{page}/"
        try:
            resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("Nie udało się pobrać %s: %s", url, e)
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        detail_links = soup.find_all("a", href=DETAIL_LINK_RE)
        if not detail_links:
            log.info("Brak ofert na stronie %s dla strefy %s - koniec", page, zone_key)
            break

        page_had_new = False
        page_max_start = None

        for a in detail_links:
            href = a["href"]
            full_url = urljoin(url, href)
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            page_had_new = True

            container = _find_offer_container(a)
            if container is None:
                continue
            block_text = container.get_text("\n")
            # normalizacja: zamieniamy wszystkie białe znaki (w tym nbsp i nowe linie)
            # na pojedyncze spacje, żeby dopasowanie regexów nie zależało od tego,
            # jak dokładnie przeglądarka/HTML łamie tekst na linie
            norm_text = re.sub(r"\s+", " ", block_text.replace("\xa0", " "))

            dates_found = DATE_LINE_RE.findall(norm_text)
            if len(dates_found) < 2:
                continue
            start_d = _parse_pl_date(*dates_found[0])
            end_d = _parse_pl_date(*dates_found[1])
            if not start_d or not end_d:
                continue

            page_max_start = max(page_max_start, start_d) if page_max_start else start_d

            if not _overlaps(start_d, end_d, target_start, target_end):
                continue

            ship = _extract_ship_name(container)
            nights_match = re.search(r"Liczba nocy:\s*(\d+)", norm_text)
            nights = int(nights_match.group(1)) if nights_match else None
            from_port_match = re.search(r"Z portu:\s*([^\n]+?)(?:\s+Do portu:|$)", norm_text)
            from_port = from_port_match.group(1).strip() if from_port_match else None

            prices = {}
            for label, raw_val in PRICE_LINE_RE.findall(norm_text):
                key = _strip_pl(label).replace(" ", "_")
                prices[key] = _parse_price(raw_val)

            if not any(v is not None for v in prices.values()):
                log.warning(
                    "Wszystkie ceny puste dla %s - fragment tekstu: %r",
                    full_url, norm_text[:300],
                )

            offers.append({
                "source": "rejsujznami.com",
                "category": zone_key,
                "ship": ship,
                "start_date": start_d.isoformat(),
                "end_date": end_d.isoformat(),
                "nights": nights,
                "route": from_port,
                "prices_eur": prices,
                "url": full_url,
            })

        if not page_had_new:
            break
        # jeśli już minęliśmy nasz zakres dat (strona posortowana rosnąco), przerywamy
        if page_max_start and page_max_start > target_end:
            log.info("Przekroczono zakres dat na stronie %s dla %s - przerywam", page, zone_key)
            break
        time.sleep(REQUEST_DELAY)

    return offers
