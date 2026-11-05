import pytest

from tiqr.core.languages import parse_currencies, parse_language, parse_languages
from tiqr.core.models import Currency
from tiqr.core.settings import Settings

KEY = "languages-suite-unique-signing-key"


def test_codes_are_normalized():
    assert parse_language(" az-az ") == "az-AZ"


@pytest.mark.parametrize("code", ["en", "xx-US", "en-FR", "english"])
def test_codes_the_app_cannot_serve_are_refused(code):
    with pytest.raises(ValueError):
        parse_language(code)


def test_repeats_collapse_and_an_empty_list_is_refused():
    assert parse_languages(["ru-RU", "ru-ru"]) == ("ru-RU",)
    with pytest.raises(ValueError, match="At least one"):
        parse_languages([])


def test_one_language_cannot_have_two_regions():
    with pytest.raises(ValueError, match="more than once"):
        parse_languages(["en-US", "en-AZ"])


def test_currencies_are_chosen_apart_from_languages():
    assert parse_currencies(["azn", "USD", "AZN"]) == (Currency.AZN, Currency.USD)
    settings = Settings(secret_key=KEY, languages=("ru-RU",), currencies=(Currency.USD,))
    assert settings.currencies == (Currency.USD,)
    with pytest.raises(ValueError, match="At least one"):
        parse_currencies([])
    with pytest.raises(ValueError, match="not supported"):
        parse_currencies(["EUR"])


def test_kazakh_is_served():
    assert parse_languages(["kk-kz", "en-US"]) == ("kk-KZ", "en-US")


def test_settings_check_branding(tmp_path):
    with pytest.raises(ValueError, match="logo_path"):
        Settings(secret_key=KEY, logo_path=tmp_path / "missing.png")
    with pytest.raises(ValueError, match="app_name"):
        Settings(secret_key=KEY, app_name=" ")
