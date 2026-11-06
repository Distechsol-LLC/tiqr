# ruff: noqa: F811 - pytest fixtures are imported by name
import json

from tests.cli.test_cli import add_user, cli_env, invoke, output_json  # noqa: F401
from tests.cli.test_cli import create_ticket as make


def printed(result):
    """The JSON a command printed, whatever its exit code."""
    return json.loads(result.output[result.output.index("{") :])


def ready():
    invoke(["setup"])
    add_user("admin", "admin")


def ticket_id():
    return output_json(make())["id"]


def test_revoke_is_idempotent_and_audited(cli_env):
    ready()
    tid = ticket_id()
    first = output_json(invoke(["ticket", "revoke", tid, "--as", "admin", "--reason", "lost"]))
    again = output_json(invoke(["ticket", "revoke", tid, "--as", "admin"]))
    assert first["state"] == again["state"] == "revoked"
    audit = output_json(invoke(["ticket", "audit", tid, "--as", "admin"]))
    assert [row["action"] for row in audit] == ["ticket.create", "ticket.revoke"]
    assert audit[1]["reason"] == "lost"
    assert cli_env[1].deactivated


def test_revoking_after_a_biostar_failure_is_refused_and_retryable(cli_env):
    ready()
    tid = ticket_id()
    registrar = cli_env[1]
    original = registrar.deactivate

    def fail(_):
        raise RuntimeError("BioStar down")

    registrar.deactivate = fail
    assert invoke(["ticket", "revoke", tid, "--as", "admin"]).exit_code == 1
    registrar.deactivate = original
    assert output_json(invoke(["ticket", "revoke", tid, "--as", "admin"]))["state"] == "revoked"


def test_update_validates_the_window(cli_env):
    ready()
    tid = ticket_id()
    ok = output_json(
        invoke(["ticket", "update", tid, "--as", "admin", "--until", "2030-01-01T16:00"])
    )
    assert ok["valid_until"].startswith("2030-01-01T16:00")
    bad = invoke(["ticket", "update", tid, "--as", "admin", "--until", "2030-01-01T10:00"])
    assert bad.exit_code == 1
    assert invoke(["ticket", "transfer", tid, "Matinee", "--as", "admin"]).exit_code != 0
    assert invoke(["ticket", "update", tid, "--as", "admin", "--reason", "x"]).exit_code != 0


def test_external_code_and_session_are_not_offered(cli_env):
    ready()
    args = [
        "ticket",
        "create",
        "-n",
        "A",
        "-t",
        "V",
        "-s",
        "V",
        "-f",
        "2030-01-01T12:00",
        "-u",
        "2030-01-01T14:00",
        "--usage",
        "one_time",
        "--as",
        "admin",
    ]
    assert invoke([*args, "--external-code", "BAR-1"]).exit_code != 0
    assert invoke([*args, "--session", "Evening"]).exit_code != 0
    assert invoke(["ticket", "list", "--as", "admin", "--external-code", "BAR-1"]).exit_code != 0


def test_idempotency_key_replays_and_conflicts(cli_env):
    ready()
    args = [
        "ticket",
        "create",
        "-n",
        "A",
        "-t",
        "V",
        "-s",
        "V",
        "-f",
        "2030-01-01T12:00",
        "-u",
        "2030-01-01T14:00",
        "--usage",
        "one_time",
        "--as",
        "admin",
        "--idempotency-key",
        "k1",
    ]
    first = output_json(invoke(args))
    assert output_json(invoke(args))["id"] == first["id"]
    other = [*args[:3], "B", *args[4:]]
    assert invoke(other).exit_code == 1
    assert len(output_json(invoke(["ticket", "list", "--as", "admin"]))) == 1


def item(**extra):
    return {
        "visitor_name": "A",
        "visitor_type": "V",
        "visitor_subtype": "V",
        "valid_from": "2030-01-01T12:00",
        "valid_until": "2030-01-01T14:00",
        "usage_type": "one_time",
    } | extra


def test_batch_partial_and_atomic(cli_env, tmp_path):
    ready()
    path = tmp_path / "b.json"
    path.write_text(json.dumps([item(), item(usage_type="multi_use"), item()]))
    partial = invoke(["ticket", "batch", str(path), "--as", "admin"])
    assert partial.exit_code == 1
    body = printed(partial)
    assert [r["status"] for r in body["results"]] == ["created", "error", "created"]
    path.write_text(json.dumps([item(), item(usage_type="multi_use"), item()]))
    atomic = invoke(["ticket", "batch", str(path), "--as", "admin", "--atomic"])
    body = printed(atomic)
    assert atomic.exit_code == 1
    assert [r["status"] for r in body["results"]] == ["rolled_back", "error", "skipped"]
    assert body["committed"] is False


def test_batch_items_need_a_subtype(cli_env, tmp_path):
    ready()
    path = tmp_path / "b.json"
    missing = item()
    del missing["visitor_subtype"]
    path.write_text(json.dumps([item(), missing, item(visitor_subtype="Visitor")]))
    result = invoke(["ticket", "batch", str(path), "--as", "admin"])
    assert result.exit_code == 1
    body = printed(result)
    assert [r["status"] for r in body["results"]] == ["created", "error", "error"]
    assert [r.get("error") for r in body["results"][1:]] == [
        "A visitor subtype is required",
        "Unknown visitor subtype",
    ]


def test_batch_size_limit(cli_env, tmp_path, monkeypatch):
    ready()
    monkeypatch.setenv("TIQR_BATCH_MAX_SIZE", "1")
    path = tmp_path / "b.json"
    path.write_text(json.dumps([item(), item()]))
    assert invoke(["ticket", "batch", str(path), "--as", "admin"]).exit_code == 1


def test_reissue_and_keys(cli_env):
    ready()
    tid = ticket_id()
    assert invoke(["ticket", "reissue", tid, "--as", "admin"]).exit_code == 0
    invoke(["ticket", "revoke", tid, "--as", "admin"])
    result = output_json(invoke(["ticket", "reissue", tid, "--as", "admin"]))
    assert (result["id"], result["state"]) == (tid, "issued")
    created = output_json(
        invoke(["key", "create", "pos", "--as", "admin", "--scope", "tickets:read"])
    )
    assert created["secret"].startswith("tqk_")
    listed = invoke(["key", "list", "--as", "admin"])
    assert created["secret"] not in listed.output
    rotated = output_json(invoke(["key", "rotate", created["id"], "--as", "admin"]))
    assert rotated["secret"] != created["secret"]
    revoked = output_json(invoke(["key", "revoke", rotated["id"], "--as", "admin"]))
    assert revoked["revoked_at"]
    assert invoke(["key", "create", "x", "--as", "admin", "--scope", "bogus"]).exit_code == 1
