"""
Konfiguracja trackera rejsów.
Tu zmieniasz zakres dat, kategorie i inne ustawienia bez grzebania w logice scrapera.
"""
from datetime import date

# Zakres dat, który nas interesuje (rejs musi się choć trochę pokrywać z tym zakresem)
TARGET_START = date(2026, 8, 20)
TARGET_END = date(2026, 8, 31)

# Kategorie do sprawdzenia na alerejsy.pl (slug używany w URL)
ALEREJSY_CATEGORIES = {
    "fiordy_europa_polnocna": "https://www.alerejsy.pl/rejsy-po-fiordach-norweskich",
    "morze_srodziemne": "https://www.alerejsy.pl/rejsy-po-morzu-srodziemnym",
}

# Strefy do sprawdzenia na rejsujznami.com (slug z polskimi znakami zakodowany w URL)
REJSUJZNAMI_ZONES = {
    "europa_polnocna": "https://www.rejsujznami.com/rejsy/z_europa_p%C3%B3%C5%82nocna/",
    "morze_srodziemne": "https://www.rejsujznami.com/rejsy/z_morze_%C5%9Br%C3%B3dziemne/",
}

# Maksymalna liczba stron paginacji do przejrzenia na kategorię (bezpiecznik)
MAX_PAGES = 60

# Nagłówki HTTP - udajemy zwykłą przeglądarkę, żeby nie być blokowanym
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "no-cache",
}

REQUEST_TIMEOUT = 20  # sekundy
REQUEST_DELAY = 1.0   # sekundy pauzy między requestami (żeby nie zamulać serwera)

DATA_DIR = "data"
LATEST_FILE = f"{DATA_DIR}/offers_latest.json"
CHANGES_FILE = f"{DATA_DIR}/changes_latest.json"
HISTORY_DIR = f"{DATA_DIR}/history"
