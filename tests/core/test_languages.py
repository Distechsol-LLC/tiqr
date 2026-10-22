import pytest

from tiqr.core.languages import currencies_for, parse_language, parse_languages
from tiqr.core.models import Currency
from tiqr.core.settings import Settings

KEY = "languages-suite-unique-signing-key"


def test_codes_are_normalized():
    assert parse_language(" az-az ") == "az-AZ"


@pytest.mark.parametrize("code", ["en", "xx-US", "en-FR", "english"])
def test_codes_the_app_cannot_serve_are_refused(code):
    with pytest.raises(ValueError):
        parse_language(code)


def test_blank_means_every_language_and_repeats_collapse():
    assert parse_languages("") == ("en-US", "ru-RU", "az-AZ")
    assert parse_languages("ru-RU, ru-ru") == ("ru-RU",)


def test_one_language_cannot_have_two_regions():
    with pytest.raises(ValueError, match="more than once"):
        parse_languages("en-US,en-AZ")


def test_currencies_follow_the_regions_in_order():
    assert currencies_for(("az-AZ", "en-US")) == (Currency.AZN, Currency.USD)
    assert Settings(secret_key=KEY, languages=("ru-RU",)).currencies == (Currency.RUB,)


def test_settings_check_branding(tmp_path):
    with pytest.raises(ValueError, match="DEFAULT_LANGUAGE"):
        Settings(secret_key=KEY, languages=("en-US",), default_language="ru-RU")
    with pytest.raises(ValueError, match="LOGO_PATH"):
        Settings(secret_key=KEY, logo_path=tmp_path / "missing.png")
    with pytest.raises(ValueError, match="APP_NAME"):
        Settings(secret_key=KEY, app_name=" ")
    assert Settings(secret_key=KEY, languages=("az-AZ", "en-US")).initial_language == "az-AZ"
