#!/usr/bin/env python3
"""Refresh public/champions.json from WWE.com and Cagematch.

The scraper intentionally treats WWE.com as the source of truth for the active
champion list. Cagematch augments those records with reign and defense data when
the title and champion can be matched confidently.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from playwright.async_api import Browser, Error as PlaywrightError, TimeoutError, async_playwright

WWE_SUPERSTARS_URL = "https://www.wwe.com/superstars"
CAGEMATCH_TITLES_URL = "https://www.cagematch.net/?id=8&nr=1&page=9"
OUTPUT_PATH = Path("public/champions.json")
NO_DEFENSE = "No Title Defenses Yet"

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

TITLE_SUFFIXES = [
    "Undisputed WWE Champion",
    "World Heavyweight Champion",
    "Women's World Champion",
    "WWE Women’s Champion",
    "WWE Women's Champion",
    "Intercontinental Champion",
    "United States Champion",
    "Women's Intercontinental Champion",
    "Women's United States Champion",
    "World Tag Team Champions",
    "WWE Tag Team Champions",
    "WWE Women's Tag Team Champions",
    "NXT Women's North American Champion",
    "NXT Women’s North American Champion",
    "NXT North American Champion",
    "NXT Women's Champion",
    "NXT Champion",
    "NXT Tag Team Champions",
    "WWE Women's Speed Champion",
    "WWE Speed Champion",
    "Evolve Men’s Champion",
    "Evolve Men's Champion",
    "Evolve Women’s Champion",
    "Evolve Women's Champion",
    "NXT Heritage Cup",
]


@dataclass
class WweChampion:
    champion_name: str
    title_name: str
    wwe_url: str
    image_url: str = ""


@dataclass
class CagematchTitle:
    title_name: str
    champion_name: str = ""
    championship_date: str | None = None
    days_as_champion: int | None = None
    last_defense_date: str | None = None
    cagematch_url: str = ""


def normalize_text(value: str | None) -> str:
    """Normalize strings so WWE.com and Cagematch naming quirks still match."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("’", "'").replace("‘", "'").replace("&", " and ")
    value = re.sub(r"[^a-zA-Z0-9\s]", " ", value)
    value = re.sub(r"\bchampions\b", "champion", value, flags=re.IGNORECASE)
    value = re.sub(r"\btitle\b", "championship", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip().lower()


def title_to_championship(value: str) -> str:
    if normalize_text(value) == "nxt heritage cup":
        return "NXT Heritage Cup Championship"
    value = value.replace("Champions", "Championship").replace("Champion", "Championship")
    return re.sub(r"\s+", " ", value).strip()


def title_to_display(value: str) -> str:
    value = re.sub(r"\s+\d{4}\s*-\s*(Present|\d{4}).*$", "", value, flags=re.IGNORECASE)
    value = value.replace("Title", "Championship")
    return re.sub(r"\s+", " ", value).strip()


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio()


def parse_date(value: str | None) -> date | None:
    if not value or value == NO_DEFENSE:
        return None
    try:
        european_date = re.search(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", value)
        if european_date:
            return date_parser.parse(european_date.group(0), dayfirst=True).date()
        return date_parser.parse(value, fuzzy=True).date()
    except (ValueError, OverflowError):
        return None


def display_date(value: str | None) -> str | None:
    parsed = parse_date(value)
    if not parsed:
        return None
    return parsed.strftime("%B %-d, %Y")


def days_between(start: date | None, end: date | None = None) -> int | None:
    if not start:
        return None
    end = end or date.today()
    return max((end - start).days, 0)


def split_champion_title(text: str) -> tuple[str, str] | None:
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in sorted(TITLE_SUFFIXES, key=len, reverse=True):
        if normalize_text(text).endswith(normalize_text(suffix)):
            champion = text[: -len(suffix)].strip()
            if champion:
                return champion, suffix
    return None


def absolutize(url: str) -> str:
    return urljoin(WWE_SUPERSTARS_URL, url)


async def new_page(browser: Browser):
    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1440, "height": 1200},
        locale="en-US",
        timezone_id="America/New_York",
    )
    page = await context.new_page()
    page.set_default_timeout(30_000)
    return context, page


async def new_cagematch_page(browser: Browser):
    context, page = await new_page(browser)

    async def route_handler(route):
        if route.request.resource_type in {"image", "font", "media", "stylesheet"}:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_handler)
    page.set_default_timeout(15_000)
    return context, page


async def fetch_html(browser: Browser, url: str) -> str:
    context, page = await new_page(browser)
    try:
        return await fetch_html_on_page(page, url)
    finally:
        await context.close()


async def fetch_html_on_page(page, url: str) -> str:
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    proceed = page.get_by_text("Click to Proceed to Page")
    if await proceed.count():
        await proceed.click(timeout=5_000)
        await page.wait_for_load_state("domcontentloaded", timeout=20_000)
        await page.wait_for_timeout(random.randint(900, 1600))
    await page.wait_for_timeout(random.randint(250, 700))
    return await page.content()


async def scrape_wwe(browser: Browser) -> list[WweChampion]:
    html = await fetch_html(browser, WWE_SUPERSTARS_URL)
    soup = BeautifulSoup(html, "html.parser")
    champions: list[WweChampion] = []
    seen: set[tuple[str, str]] = set()

    # WWE.com's champion area is exposed as linked text like
    # "Cody Rhodes Undisputed WWE Champion"; parse only those known suffixes.
    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(" ", strip=True)
        parsed = split_champion_title(text)
        if not parsed:
            continue

        champion_name, title_name = parsed
        key = (normalize_text(champion_name), normalize_text(title_name))
        if key in seen:
            continue
        seen.add(key)

        champions.append(
            WweChampion(
                champion_name=champion_name,
                title_name=title_name,
                wwe_url=absolutize(anchor["href"]),
                image_url=extract_listing_image(anchor),
            )
        )

    await enrich_wwe_images(browser, champions)
    return champions


async def enrich_wwe_images(browser: Browser, champions: list[WweChampion]) -> None:
    for champion in champions:
        if champion.image_url:
            continue

        try:
            html = await fetch_html(browser, champion.wwe_url)
        except PlaywrightError:
            continue

        soup = BeautifulSoup(html, "html.parser")
        image_url = extract_profile_image(soup)
        if image_url:
            champion.image_url = image_url


def extract_profile_image(soup: BeautifulSoup) -> str:
    # WWE profile pages commonly expose the headshot through Open Graph first.
    for selector in [
        ('meta', {'property': 'og:image'}),
        ('meta', {'name': 'twitter:image'}),
    ]:
        tag = soup.find(*selector)
        content = tag.get("content") if tag else ""
        if content:
            return str(content)

    # Fallback to the first large image-like source on the profile page.
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src and not src.startswith("data:"):
            return absolutize(src)
    return ""


def extract_listing_image(anchor) -> str:
    """Prefer the champion card image from WWE.com's listing.

    This is especially important for tag titles: profile-page Open Graph images
    often point at one wrestler, while the listing card has the current team art.
    """
    parent = anchor
    for _ in range(4):
        parent = parent.parent if parent else None
        if not parent:
            break

        classes = set(parent.get("class") or [])
        if classes.intersection({"talent-details", "championship-details", "field__item"}):
            image = parent.find("img")
            src = (image.get("src") or image.get("data-src")) if image else ""
            if src and not src.startswith("data:"):
                return absolutize(src)
    return ""


async def scrape_cagematch(browser: Browser) -> list[CagematchTitle]:
    html = ""
    context, page = await new_page(browser)
    try:
        for _ in range(3):
            try:
                html = await fetch_html_on_page(page, CAGEMATCH_TITLES_URL)
                if "Active Titles" in BeautifulSoup(html, "html.parser").get_text("\n", strip=True):
                    break
            except (PlaywrightError, TimeoutError):
                await asyncio.sleep(1)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        titles = extract_active_cagematch_titles(soup)
        await enrich_cagematch_defenses(page, titles)
        return titles
    finally:
        await context.close()


async def enrich_cagematch_defenses(page, titles: list[CagematchTitle]) -> None:
    for title in titles:
        if not title.cagematch_url:
            continue

        try:
            detail_html = await fetch_html_on_page(page, title.cagematch_url)
        except (PlaywrightError, TimeoutError):
            continue

        matches_url = find_current_reign_matches_url(detail_html, title.cagematch_url)
        if not matches_url:
            continue

        try:
            matches_html = await fetch_html_on_page(page, matches_url)
        except (PlaywrightError, TimeoutError):
            continue

        title.last_defense_date = parse_last_defense_from_matches(matches_html)


def find_current_reign_matches_url(html: str, title_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "id=5" in href and "page=5" in href and "reign=" in href:
            return urljoin(title_url, href)
    return ""


def parse_last_defense_from_matches(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    data_rows = [row for row in extract_table_rows(soup) if row and row[0].isdigit()]
    if len(data_rows) <= 1:
        return None

    newest_row = data_rows[0]
    if len(newest_row) < 2:
        return None
    return display_date(newest_row[1])


def extract_active_cagematch_titles(soup: BeautifulSoup) -> list[CagematchTitle]:
    titles: list[CagematchTitle] = []
    for row in extract_table_rows(soup):
        if len(row) < 4 or not row[0].isdigit():
            continue

        title_name = title_to_display(row[1])
        champion_name = re.sub(r"\s*\(\d+\)\s*$", "", row[2]).strip()
        since_text = row[3]
        since_date = display_date(since_text)
        days_match = re.search(r"\((\d+)\s*(?:Tage|days?)\)", since_text, flags=re.IGNORECASE)
        days_as_champion = int(days_match.group(1)) if days_match else days_between(parse_date(since_text))
        cagematch_url = find_title_url(soup, title_name)

        if title_name and champion_name and champion_name.upper() != "INACTIVE" and cagematch_url:
            titles.append(
                CagematchTitle(
                    title_name=title_name,
                    champion_name=champion_name,
                    championship_date=since_date,
                    days_as_champion=days_as_champion,
                    cagematch_url=cagematch_url,
                )
            )
    return titles


def find_title_url(soup: BeautifulSoup, title_name: str) -> str:
    target = normalize_text(title_name)
    for anchor in soup.find_all("a", href=True):
        if "id=5" not in anchor["href"] or "nr=" not in anchor["href"]:
            continue
        if normalize_text(anchor.get_text(" ", strip=True)) == target:
            return urljoin("https://www.cagematch.net/", anchor["href"])
    return ""


def extract_cagematch_title_links(soup: BeautifulSoup) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Cagematch title rows link to pages like ?id=5&nr=20. Keep WWE title-ish
    # rows and skip retired date ranges later through fuzzy matching.
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        text = title_to_display(anchor.get_text(" ", strip=True))
        if not text or "id=5" not in href:
            continue

        normalized = normalize_text(text)
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append((text, urljoin("https://www.cagematch.net/", href)))

    return links


def parse_cagematch_title_page(html: str, title_name: str, url: str) -> CagematchTitle:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    rows = extract_table_rows(soup)

    champion_name = find_labeled_value(text, ["Current champion", "Current Champions", "Champion"])
    championship_date = find_date_after_labels(rows, ["Won", "Date", "Since"])
    days_as_champion = find_days_as_champion(text)
    last_defense_date = find_last_defense_date(rows, text)

    return CagematchTitle(
        title_name=title_to_display(title_name),
        champion_name=champion_name or "",
        championship_date=display_date(championship_date),
        days_as_champion=days_as_champion,
        last_defense_date=display_date(last_defense_date),
        cagematch_url=url,
    )


def extract_table_rows(soup: BeautifulSoup) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def find_labeled_value(text: str, labels: Iterable[str]) -> str | None:
    for label in labels:
        pattern = rf"{re.escape(label)}\s*:?\s*([^\n]+)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def find_date_after_labels(rows: list[list[str]], labels: Iterable[str]) -> str | None:
    for row in rows:
        joined = " | ".join(row)
        if not any(label.lower() in joined.lower() for label in labels):
            continue
        for cell in row:
            parsed = parse_date(cell)
            if parsed:
                return cell

    for row in rows:
        for cell in row:
            parsed = parse_date(cell)
            if parsed and 1950 <= parsed.year <= datetime.now().year:
                return cell
    return None


def find_days_as_champion(text: str) -> int | None:
    patterns = [
        r"(\d+)\s+days?\s+as\s+champion",
        r"days\s*:?\s*(\d+)",
        r"reign\s*:?\s*(\d+)\s+days?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def find_last_defense_date(rows: list[list[str]], text: str) -> str | None:
    if re.search(r"no\s+title\s+defen[cs]es", text, flags=re.IGNORECASE):
        return None

    dated_rows: list[date] = []
    for row in rows:
        joined = " ".join(row)
        if not re.search(r"defen[cs]e|defended|retained", joined, flags=re.IGNORECASE):
            continue
        for cell in row:
            parsed = parse_date(cell)
            if parsed:
                dated_rows.append(parsed)

    if not dated_rows:
        return None
    return max(dated_rows).strftime("%B %-d, %Y")


def match_cagematch(wwe: WweChampion, cagematch_titles: list[CagematchTitle]) -> CagematchTitle | None:
    wwe_title = title_to_championship(wwe.title_name)
    exact = [
        title
        for title in cagematch_titles
        if normalize_text(title.title_name) == normalize_text(wwe_title)
        or normalize_text(title.title_name) == normalize_text(wwe.title_name)
    ]
    if exact:
        return best_champion_match(wwe, exact)

    scored = []
    for title in cagematch_titles:
        title_score = max(similarity(wwe.title_name, title.title_name), similarity(wwe_title, title.title_name))
        champion_score = similarity(wwe.champion_name, title.champion_name) if title.champion_name else 0.5
        score = title_score * 0.75 + champion_score * 0.25
        if title_score >= 0.74:
            scored.append((score, title))

    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored[0][0] >= 0.68 else None


def best_champion_match(wwe: WweChampion, titles: list[CagematchTitle]) -> CagematchTitle:
    return max(
        titles,
        key=lambda title: similarity(wwe.champion_name, title.champion_name) if title.champion_name else 0,
    )


def combine_records(wwe_champions: list[WweChampion], cagematch_titles: list[CagematchTitle]) -> list[dict]:
    records: list[dict] = []
    today = date.today()

    for champion in wwe_champions:
        matched = match_cagematch(champion, cagematch_titles)
        championship_date = matched.championship_date if matched else None
        last_defense_date = matched.last_defense_date if matched and matched.last_defense_date else NO_DEFENSE
        defense_date = parse_date(last_defense_date)
        reign_start = parse_date(championship_date)

        records.append(
            {
                "titleName": champion.title_name,
                "championName": champion.champion_name,
                "imageUrl": champion.image_url,
                "championshipDate": championship_date,
                "daysAsChampion": matched.days_as_champion if matched and matched.days_as_champion is not None else days_between(reign_start, today),
                "lastDefenseDate": last_defense_date,
                "daysSinceLastDefense": days_between(defense_date, today) if defense_date else None,
                "source": {
                    "wweUrl": champion.wwe_url,
                    "cagematchUrl": matched.cagematch_url if matched else "",
                },
            }
        )

    return records


async def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            cagematch_titles = await scrape_cagematch(browser)
            wwe_champions = await scrape_wwe(browser)
        finally:
            await browser.close()

    if not cagematch_titles:
        cagematch_titles = existing_cache_as_cagematch_titles(OUTPUT_PATH)
        print("Cagematch scrape returned no titles; preserving existing cached Cagematch metadata.")

    records = combine_records(wwe_champions, cagematch_titles)
    OUTPUT_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} champion records to {OUTPUT_PATH}")


def existing_cache_as_cagematch_titles(path: Path) -> list[CagematchTitle]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    titles: list[CagematchTitle] = []
    for item in data if isinstance(data, list) else []:
        source = item.get("source") if isinstance(item, dict) else {}
        if not isinstance(source, dict) or not source.get("cagematchUrl"):
            continue
        titles.append(
            CagematchTitle(
                title_name=title_to_championship(str(item.get("titleName") or "")),
                champion_name=str(item.get("championName") or ""),
                championship_date=item.get("championshipDate"),
                days_as_champion=item.get("daysAsChampion"),
                last_defense_date=None
                if item.get("lastDefenseDate") == NO_DEFENSE
                else item.get("lastDefenseDate"),
                cagematch_url=str(source.get("cagematchUrl") or ""),
            )
        )
    return titles


if __name__ == "__main__":
    asyncio.run(main())
