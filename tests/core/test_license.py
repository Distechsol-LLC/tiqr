from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization

from tiqr.core.license import (
    LicenseError,
    LicenseState,
    build_request_code,
    machine_id,
    parse_request_code,
    verify_license_key,
)
from tiqr.core.service import PermissionDeniedError


@pytest.fixture
def licensed(service):
    return service


@pytest.fixture
def pair(license_pair):
    return license_pair


def _pair():
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa  # noqa: PLC0415

    key = _rsa.generate_private_key(65537, 2048)
    return None, key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def test_machine_id_is_stable_hex():
    assert machine_id() == machine_id()
    assert len(machine_id()) == 32
    assert machine_id() == machine_id().upper()


def test_request_code_roundtrip_and_strict_parse():
    request = parse_request_code(build_request_code("trial"))
    assert request.machine_id == machine_id()
    assert request.request_type == "trial"
    for bad in ("", "!!!", "e30=", "bnVsbA=="):
        with pytest.raises(ValueError, match="request"):
            parse_request_code(bad)


def test_verify_rejects_tampering(issue, pair):
    key = issue()
    assert verify_license_key(key, pair[1]) is not None
    payload, signature = key.split(".")
    assert verify_license_key(f"{payload}A.{signature}", pair[1]) is None
    assert verify_license_key(key + ".x", pair[1]) is None
    assert verify_license_key(key, _pair()[1]) is None
    assert verify_license_key("garbage", pair[1]) is None


def test_verify_rejects_other_product(issue, pair):
    assert verify_license_key(issue(product="other"), pair[1]) is None


def test_status_none_then_active(licensed, accounts, issue):
    assert licensed.license_status().state == LicenseState.NONE
    status = licensed.activate_license(accounts["admin"], issue())
    assert status.state == LicenseState.ACTIVE
    assert status.is_valid
    assert status.days_remaining == 365
    assert status.machine_id == machine_id()


def test_trial_status(licensed, accounts, issue):
    status = licensed.activate_license(accounts["admin"], issue("trial"))
    assert status.state == LicenseState.ACTIVE
    assert status.type == "trial"
    assert status.days_remaining == 30


def test_expiry_comes_from_the_key_not_the_database(licensed, accounts, issue, clock):
    licensed.activate_license(accounts["admin"], issue(days=1))
    clock.now += timedelta(days=2)
    status = licensed.license_status()
    assert status.state == LicenseState.EXPIRED
    assert not status.is_valid
    assert status.licensed_to == "Acme"


def test_stored_key_that_stops_verifying_is_invalid(licensed, accounts, issue, repository):
    licensed.activate_license(accounts["admin"], issue())
    repository._connection.execute("UPDATE licenses SET license_key='x.y'")
    assert licensed.license_status().state == LicenseState.INVALID


def test_key_copied_to_another_machine_is_invalid(licensed, accounts, issue, monkeypatch):
    licensed.activate_license(accounts["admin"], issue())
    monkeypatch.setattr("tiqr.core.service.machine_id", lambda: "B" * 32)
    status = licensed.license_status()
    assert status.state == LicenseState.INVALID
    assert not status.is_valid


def test_wrong_machine_is_refused(licensed, accounts, issue):
    with pytest.raises(LicenseError) as error:
        licensed.activate_license(accounts["admin"], issue(machine="A" * 32))
    assert error.value.code == "license_wrong_machine"


def test_empty_machine_is_not_a_wildcard(licensed, accounts, issue):
    with pytest.raises(LicenseError) as error:
        licensed.activate_license(accounts["admin"], issue(machine=""))
    assert error.value.code == "license_wrong_machine"


def test_expired_key_is_refused_and_old_license_survives(licensed, accounts, issue):
    licensed.activate_license(accounts["admin"], issue())
    with pytest.raises(LicenseError) as error:
        licensed.activate_license(accounts["admin"], issue(days=0))
    assert error.value.code == "license_already_expired"
    with pytest.raises(LicenseError) as bad:
        licensed.activate_license(accounts["admin"], "nope.nope")
    assert bad.value.code == "license_bad_signature"
    assert licensed.license_status().state == LicenseState.ACTIVE


def test_trial_cannot_replace_paid(licensed, accounts, issue):
    licensed.activate_license(accounts["admin"], issue())
    with pytest.raises(LicenseError) as error:
        licensed.activate_license(accounts["admin"], issue("trial"))
    assert error.value.code == "license_trial_over_paid"
    assert error.value.status == 409


def test_same_key_cannot_be_pasted_twice(licensed, accounts, issue):
    key = issue("trial")
    licensed.activate_license(accounts["admin"], key)
    with pytest.raises(LicenseError) as error:
        licensed.activate_license(accounts["admin"], key)
    assert error.value.code == "license_already_active"
    assert [row.is_active for row in licensed.license_history(accounts["admin"])] == [True]


def test_trial_cannot_replace_expired_paid(licensed, accounts, issue, clock):
    licensed.activate_license(accounts["admin"], issue(days=30))
    clock.now += timedelta(days=31)
    with pytest.raises(LicenseError) as error:
        licensed.activate_license(accounts["admin"], issue("trial"))
    assert error.value.code == "license_trial_over_paid"


def test_paid_replaces_trial_and_history_is_kept(licensed, accounts, issue):
    licensed.activate_license(accounts["admin"], issue("trial"))
    licensed.activate_license(accounts["admin"], issue())
    history = licensed.license_history(accounts["admin"])
    assert [row.is_active for row in history] == [True, False]


def test_only_admins_manage_licenses(licensed, accounts, issue):
    for role in ("manager", "operator"):
        with pytest.raises(PermissionDeniedError):
            licensed.activate_license(accounts[role], issue())
        with pytest.raises(PermissionDeniedError):
            licensed.license_history(accounts[role])
    assert licensed.license_request_code(accounts["operator"])


def test_card_with_a_temporary_address_keeps_its_permanent_one(tmp_path, monkeypatch):
    """Wi-Fi managers randomize the address while scanning; the machine ID must not follow it."""
    from tiqr.core import license as module  # noqa: PLC0415

    card = tmp_path / "wlan0"
    (card / "device").mkdir(parents=True)
    (card / "addr_assign_type").write_text("3\n")
    monkeypatch.setattr(module, "_permanent_mac", lambda _: "04:f0:ee:42:13:2d")
    seen = set()
    for live in ("62:35:e0:e7:0c:47", "04:f0:ee:42:13:2d"):
        (card / "address").write_text(live + "\n")
        seen.add(module._card_mac(card))
    assert seen == {"04:f0:ee:42:13:2d"}


def test_card_with_a_temporary_address_and_no_permanent_one_is_skipped(tmp_path, monkeypatch):
    from tiqr.core import license as module  # noqa: PLC0415

    card = tmp_path / "wlan0"
    (card / "device").mkdir(parents=True)
    (card / "addr_assign_type").write_text("1\n")
    (card / "address").write_text("62:35:e0:e7:0c:47\n")
    monkeypatch.setattr(module, "_permanent_mac", lambda _: None)
    assert module._card_mac(card) == ""
