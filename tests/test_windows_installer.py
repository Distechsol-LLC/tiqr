"""The Windows installer script keeps the lists it cannot import in step with the app.

packaging/windows/tiqr.iss is Pascal, so these tests read it as text: every theme, language,
default and key it names must match what the app accepts, so a change there fails here first.
"""

import re
from pathlib import Path
from zoneinfo import ZoneInfo

from tiqr.core import settings
from tiqr.core.languages import DEFAULT_LANGUAGES, SUPPORTED_LANGUAGES, parse_language
from tiqr.core.qr import DEFAULT_PREFIX

PROJECT = Path(__file__).resolve().parents[1]
WINDOWS = PROJECT / "packaging" / "windows"
SCRIPT = (WINDOWS / "tiqr.iss").read_text(encoding="utf-8")


def _constant(name: str) -> str:
    match = re.search(rf"^\s*{name} = '([^']*)';", SCRIPT, re.MULTILINE)
    assert match, f"{name} is not defined in tiqr.iss"
    return match[1]


def test_every_web_theme_is_offered() -> None:
    web = (PROJECT / "apps" / "web" / "src" / "data" / "themes.ts").read_text(encoding="utf-8")
    themes = set(re.findall(r"'([a-z]+)',", web))
    offered = _constant("ThemeNames").split("|")
    assert len(offered) == len(set(offered)) == 24
    assert set(offered) == themes
    assert _constant("DefaultThemeName") in offered
    # The constructor's default value for the vintage look.
    assert _constant("DefaultThemeValue") == settings.DEFAULT_THEME


def test_languages_are_the_apps() -> None:
    codes = _constant("LanguageCodes").split("|")
    assert [parse_language(code) for code in codes] == codes
    assert {code.partition("-")[0] for code in codes} == SUPPORTED_LANGUAGES
    assert tuple(_constant("DefaultLanguages").split("|")) == DEFAULT_LANGUAGES
    assert len(_constant("LanguageLabels").split("|")) == len(codes)


def test_defaults_are_the_constructors() -> None:
    assert _constant("DefaultPrefix") == DEFAULT_PREFIX
    assert _constant("DefaultHost") == "127.0.0.1"
    assert _constant("DefaultPort") == "7102"
    assert _constant("DefaultBioTimeout") == "30"
    assert _constant("DefaultBioDoorDuration") == "3"
    assert _constant("DefaultBioDoorTimeout") == "10"
    assert {*_constant("LogoExtensions").split("|")} == settings.LOGO_SUFFIXES


def test_generator_writes_the_schemas_keys_in_order() -> None:
    template = settings._jsonc_loads((PROJECT / "tiqr_brand.jsonc").read_text(encoding="utf-8"))
    assert isinstance(template, dict)
    expected = [key for key in template if key != "biostar"] + [
        f"biostar.{key}" for key in template["biostar"]
    ]
    written = [
        ("biostar." if len(indent) == 4 else "") + key
        for indent, key in re.findall(r"Entry\('( +)', '(\w+)'", SCRIPT)
    ]
    assert written == expected
    assert {key.removeprefix("biostar.") for key in expected} >= set(settings._BIOSTAR_KEYS)


def test_theme_page_links_the_skeleton_themes() -> None:
    assert '#define SkeletonThemesUrl "https://skeleton.dev/docs/svelte/design/themes"' in SCRIPT
    assert "Link.OnClick := @ThemeLinkClick" in SCRIPT


def test_timezone_list_is_valid_and_complete() -> None:
    names = (WINDOWS / "timezones.txt").read_text(encoding="ascii").splitlines()
    assert names == sorted(set(names))
    assert {"UTC", "Asia/Baku", "Europe/Moscow", "Asia/Almaty"} <= set(names)
    for name in names:
        ZoneInfo(name)


def test_a_reinstall_asks_then_starts_from_scratch() -> None:
    assert "function InitializeSetup" in SCRIPT
    assert "DirExists(ExpandConstant('{autopf}\\TiQR'))" in SCRIPT
    assert "DirExists(ExpandConstant('{commonappdata}\\TiQR'))" in SCRIPT
    assert "procedure RemoveExistingInstall;" in SCRIPT
    assert "DelTree(DataFolder, True, True, True);" in SCRIPT
    assert "else if Reinstalling then\n    RemoveExistingInstall;" in SCRIPT
    assert "set TIQR_REINSTALL_CONFIRMED=1" in SCRIPT


def test_install_and_uninstall_cover_only_generated_files() -> None:
    assert 'Excludes: "tiqr_brand.jsonc,' in SCRIPT
    assert 'Source: "{tmp}\\tiqr_brand.jsonc"' in SCRIPT
    deleted = re.findall(r'^Type: files; Name: "([^"]+)"', SCRIPT, re.MULTILINE)
    assert deleted
    assert all(name.startswith(("{app}\\", "{commonappdata}\\TiQR\\")) for name in deleted)
