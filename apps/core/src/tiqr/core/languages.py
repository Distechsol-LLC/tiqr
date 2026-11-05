"""The languages and the currencies an install offers; each is chosen on its own."""

import re
from collections.abc import Iterable

from tiqr.core.models import Currency

# The web app is translated into these; a language needs a translation there before it is listed.
SUPPORTED_LANGUAGES = frozenset({"en", "ru", "az", "kk"})
# The region of a language code picks its flag; it says nothing about currency.
REGIONS = frozenset({"US", "RU", "AZ", "KZ"})
DEFAULT_LANGUAGES = ("en-US", "ru-RU", "az-AZ")
DEFAULT_CURRENCIES = (Currency.USD, Currency.RUB, Currency.AZN)

_CODE = re.compile(r"(?P<language>[A-Za-z]{2})-(?P<region>[A-Za-z]{2})")


def parse_language(code: str) -> str:
    """Normalize a code such as az-az to az-AZ, refusing what the app cannot serve."""
    match = _CODE.fullmatch(code.strip())
    if match is None:
        raise ValueError(f"Language {code!r} must look like en-US: a language and a region")
    language, region = match["language"].lower(), match["region"].upper()
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Language {language!r} is not supported; use {', '.join(sorted(SUPPORTED_LANGUAGES))}"
        )
    if region not in REGIONS:
        raise ValueError(f"Region {region!r} is not supported; use {', '.join(sorted(REGIONS))}")
    return f"{language}-{region}"


def parse_languages(codes: Iterable[str]) -> tuple[str, ...]:
    """Normalize the codes, dropping repeats; the first is the fallback default."""
    codes = list(codes)
    if not codes:
        raise ValueError("At least one language is required")
    parsed = tuple(dict.fromkeys(parse_language(code) for code in codes))
    if len({code.partition("-")[0] for code in parsed}) != len(parsed):
        raise ValueError("languages lists a language more than once")
    return parsed


def parse_currencies(codes: Iterable[str]) -> tuple[Currency, ...]:
    """Normalize codes such as usd to currencies, dropping repeats; at least one is required."""
    parsed: list[Currency] = []
    for code in codes:
        try:
            parsed.append(Currency(code.strip().upper()))
        except ValueError:
            names = ", ".join(currency.value for currency in Currency)
            raise ValueError(f"Currency {code!r} is not supported; use {names}") from None
    if not parsed:
        raise ValueError("At least one currency is required")
    return tuple(dict.fromkeys(parsed))
