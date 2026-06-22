"""CLI smoke tests — argument routing and exit codes for the offline commands."""
import json

import pytest

from hallucheck import cli


def test_emit_prompt(capsys):
    assert cli.main(["emit-prompt", "--adapter", "maine", "--scope", "DE-101"]) == 0
    assert "ALLOWED CITATIONS" in capsys.readouterr().out


def test_bench_exits_zero_and_reports(capsys):
    assert cli.main(["bench", "--adapter", "maine"]) == 0
    assert "precision=1.0" in capsys.readouterr().out


def test_sources_json(capsys):
    assert cli.main(["sources", "--adapter", "maine", "--cite", "2000 ME 17", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kind"] == "case" and out["links"]


def test_scan_flags_invented_cite(tmp_path, capsys):
    draft = tmp_path / "d.txt"
    draft.write_text("The court must rule for us under 18-C §9-999.", encoding="utf-8")
    rc = cli.main(["scan", "--adapter", "maine", "--draft", str(draft)])
    assert rc == 1                                   # leaked + unresolvable -> nonzero
    assert "9-999" in capsys.readouterr().out


def test_pack_md_to_file(tmp_path):
    out = tmp_path / "pack.md"
    rc = cli.main(["pack", "--adapter", "maine", "--cite", "18-C §3-108",
                   "--no-fetch", "--format", "md", "--out", str(out)])
    assert rc == 0
    assert "Citation Verification Packet" in out.read_text(encoding="utf-8")


def test_pack_unresolved_returns_nonzero(tmp_path):
    out = tmp_path / "p.md"
    rc = cli.main(["pack", "--adapter", "maine", "--cite", "18-C §9-999",
                   "--no-fetch", "--format", "md", "--out", str(out)])
    assert rc == 1                                   # unverified cite -> nonzero


def test_verify_log_missing(capsys):
    assert cli.main(["verify-log", "/nonexistent/log.jsonl"]) == 1


def test_unknown_command_errors():
    with pytest.raises(SystemExit):
        cli.main(["nope"])
