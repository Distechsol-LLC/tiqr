"""The languages an install offers, and the currencies that follow from them."""

import re
from collections.abc import Iterable

from tiqr.core.models import Currency

# The web app is translated into these; a language needs a translation there before it is listed.
SUPPORTED_LANGUAGES = frozenset({"en", "ru", "az"})
# The region of a language code names the currency its speakers pay in.
REGION_CURRENCIES = {"US": Currency.USD, "RU": Currency.RUB, "AZ": Currency.AZN}
DEFAULT_LANGUAGES = ("en-US", "ru-RU", "az-AZ")

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
    if region not in REGION_CURRENCIES:
        raise ValueError(
            f"Region {region!r} has no currency; use {', '.join(sorted(REGION_CURRENCIES))}"
        )
    return f"{language}-{region}"


def parse_languages(value: str) -> tuple[str, ...]:
    """Split a comma-separated list; blank means every language. Order is kept."""
    codes = [part for part in value.split(",") if part.strip()]
    if not codes:
        return DEFAULT_LANGUAGES
    parsed = tuple(dict.fromkeys(parse_language(code) for code in codes))
    if len({code.partition("-")[0] for code in parsed}) != len(parsed):
        raise ValueError("TIQR_LANGUAGES lists a language more than once")
    return parsed


def currencies_for(languages: Iterable[str]) -> tuple[Currency, ...]:
    """The currencies of the languages' regions, in language order, without repeats."""
    return tuple(dict.fromkeys(REGION_CURRENCIES[code.partition("-")[2]] for code in languages))
