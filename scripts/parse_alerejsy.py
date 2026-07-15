"""
Parser dla alerejsy.pl

Strategia: zamiast polegać na konkretnych klasach CSS (które mogą się zmienić
i których nie mogliśmy zweryfikować z tego środowiska bez dostępu do sieci),
szukamy "kotwic" po widocznym tekście i strukturze linków, które są dużo
bardziej stabilne:
  - link do szczegółów oferty pasuje do wzorca /rejsy/<slug>-RRRR-MM-DD-<dni>...
  - w tym samym bloku znajduje się data w formacie "DD.MM - DD.MM.RRRR (N dni)"
  - dalej etykiety "Kabina wewnętrzna", "Kabina z oknem", "Kabina z balkonem", "Apartament"

Jeśli struktura strony się zmieni na tyle, że to przestanie działać, skrypt
zaloguje ostrzeżenie i przynajmniej nie wywali się na starcie - da się to
łatwo zdebugować patrząc na zapisane surowe HTML w data/debug/.
"""
import re
import time
import logging
from datetime import date, datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY, MAX_PAGES

log = logging.getLogger("alerejsy")

DETAIL_LINK_RE = re.compile(r"/rejsy/[a-z0-9\-]+-\d{4}-\d{2}-\d{2}-\d+")
DATE_RANGE_RE = re.compile(
    r"(\d{2}\.\d{2})\s*-\s*(\d{2}\.\d{2}\.\d{4})\s*\((\d+)\s*dni\)"
)
ROUTE_RE = re.compile(r"trasa:\s*(.+?)(?:\s*Cena za osob|\s*\*ceny|$)")
PRICE_LABELS = ["Kabina wewnętrzna", "Kabina z oknem", "Kabina z balkonem", "Apartament"]


def _parse_price(text):
    """Zamienia '699 €' / 'od 699 €' / 'zadzwoń' / 'brak' na liczbę albo None."""
    if not text:
        return None
    text = text.strip()
    m = re.search(r"([\d\s]+)\s*€", text)
    if m:
        try:
            return int(m.group(1).replace(" ", "").replace("\xa0", ""))
        except ValueError:
            return None
    return None  # 'zadzwoń', 'brak', puste itp.


_PRICE_BLOCK_RE = re.compile(
    "(" + "|".join(re.escape(l) for l in PRICE_LABELS) + r")\s*"
    r"(od\s*[\d\s]+\s*€|zadzwoń|brak|n\.d\.)",
    re.IGNORECASE,
)


def _extract_prices(normalized_text):
    """Wyciąga ceny 4 typów kabin z jednoliniowego, znormalizowanego tekstu bloku oferty."""
    prices = {}
    for label, raw_val in _PRICE_BLOCK_RE.findall(normalized_text):
        key = label.lower().replace("kabina ", "").replace(" ", "_")
        prices[key] = _parse_price(raw_val)
    return prices


def _find_offer_container(a_tag):
    """Idzie w górę drzewa DOM aż znajdzie kontener zawierający datę i ceny."""
    node = a_tag
    for _ in range(6):
        if node is None:
            break
        text = node.get_text("\n")
        if DATE_RANGE_RE.search(text) and "Kabina" in text:
            return node
        node = node.parent
    return None


def _extract_ship_name(container, detail_href):
    """Nazwa statku to zwykle najbliższy <a> do strony statku (/statek/...)."""
    ship_link = container.find("a", href=re.compile(r"/statek/"))
    if ship_link:
        name = ship_link.get_text(strip=True)
        if name:
            return name
    # fallback: pierwsza pogrubiona linia tekstu
    strong = container.find("strong")
    if strong:
        return strong.get_text(strip=True)
    return None


def _departs_in_range(start_d, target_start, target_end):
    """Rejs kwalifikuje się, jeśli DATA WYPŁYNIĘCIA mieści się w zadanym zakresie
    (a nie tylko jakikolwiek dzień rejsu nakłada się z zakresem)."""
    return target_start <= start_d <= target_end


def scrape_category(category_key, base_url, target_start, target_end, session=None):
    """Scrapuje jedną kategorię (wszystkie strony paginacji) i zwraca listę ofert."""
    session = session or requests.Session()
    offers = []
    seen_links = set()

    # "Rozgrzewka" - odwiedzamy stronę główną, żeby dostać normalne ciasteczka sesji,
    # zanim wejdziemy na stronę kategorii. Niektóre zabezpieczenia antybotowe (WAF)
    # blokują (np. błędem 415) pierwsze żądanie idące bezpośrednio na podstronę.
    if not session.cookies:
        try:
            session.get("https://www.alerejsy.pl/", headers=HEADERS, timeout=REQUEST_TIMEOUT)
            time.sleep(REQUEST_DELAY)
        except requests.RequestException as e:
            log.warning("Rozgrzewka (strona główna) nie powiodła się: %s", e)

    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("Nie udało się pobrać %s: %s", url, e)
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        detail_links = soup.find_all("a", href=DETAIL_LINK_RE)

        if not detail_links:
            log.info("Brak ofert na stronie %s (koniec paginacji albo zmieniona struktura)", page)
            if page == 1:
                title = soup.title.get_text(strip=True) if soup.title else "(brak <title>)"
                visible_text = soup.get_text(" ", strip=True)[:400]
                log.warning(
                    "DIAGNOSTYKA %s: status=%s, dlugosc_html=%s, title=%r, poczatek_tekstu=%r",
                    category_key, resp.status_code, len(resp.text), title, visible_text,
                )
            break

        page_had_new = False
        for a in detail_links:
            href = a["href"]
            full_url = urljoin(url, href)
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            page_had_new = True

            container = _find_offer_container(a)
            if container is None:
                log.warning("Nie znaleziono kontenera oferty dla linku %s", full_url)
                continue

            raw_block_text = container.get_text("\n")
            # normalizacja: wszystkie białe znaki (nbsp, nowe linie) -> pojedyncza spacja,
            # żeby dopasowanie nie zależało od dokładnej struktury HTML
            block_text = re.sub(r"\s+", " ", raw_block_text.replace("\xa0", " "))
            date_match = DATE_RANGE_RE.search(block_text)
            if not date_match:
                continue

            end_str = date_match.group(2)
            nights = int(date_match.group(3))
            try:
                end_d = datetime.strptime(end_str, "%d.%m.%Y").date()
            except ValueError:
                continue
            # data startu: dzień.miesiąc z pierwszej części + rok/miesiąc z end (przybliżenie,
            # poprawiane niżej jeśli miesiąc startu != miesiąc końca przez odjęcie 'nights')
            start_day_month = date_match.group(1)
            try:
                start_d = datetime.strptime(f"{start_day_month}.{end_d.year}", "%d.%m.%Y").date()
                if start_d > end_d:
                    start_d = start_d.replace(year=end_d.year - 1)
            except ValueError:
                continue

            if not _departs_in_range(start_d, target_start, target_end):
                continue

            ship = _extract_ship_name(container, href)
            route_match = ROUTE_RE.search(block_text)
            route = route_match.group(1).strip() if route_match else None
            prices = _extract_prices(block_text)

            if not any(v is not None for v in prices.values()):
                log.warning(
                    "Wszystkie ceny puste dla %s - fragment tekstu: %r",
                    full_url, block_text[:300],
                )

            offers.append({
                "source": "alerejsy.pl",
                "category": category_key,
                "ship": ship,
                "start_date": start_d.isoformat(),
                "end_date": end_d.isoformat(),
                "nights": nights,
                "route": route,
                "prices_eur": prices,
                "url": full_url,
            })

        if not page_had_new:
            break
        time.sleep(REQUEST_DELAY)

    return offers
