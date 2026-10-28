"""The command line and the upload page, with the model scripted and no network."""

import json
from datetime import date

import asas_agent
import pytest
from conftest import FIXTURES, Scripted, docx, lines, run

from asas_cv_profile import ProfileBuilder, cli, write_outputs


def built_profile(model):
    def answer(call, s):
        if s.name == "Name":
            return {"full_name": "Sara Example", "lines": [[1, 1]]}
        return None

    text = lines("Sara Example", "EXPERIENCE", "Analyst, Example Co, 2019-2021")
    return run(ProfileBuilder(model, Scripted(model, answer)).build(b"x", "cv.txt", as_of=date(2026, 10, 28), text=text))


def test_schema_lists_the_calls(capsys):
    assert cli.main(["schema", "--profile-model", str(FIXTURES / "profile.yaml"), "--split"]) == 0
    assert "ProfileGroup1:" in capsys.readouterr().out


def test_a_bad_profile_model_exits_with_where_it_is_wrong(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("sections: [{name: A, fields: [{name: B, type: money}]}]")
    assert cli.main(["schema", "--profile-model", str(bad)]) == 2
    assert "unknown type 'money'" in capsys.readouterr().err


def test_a_model_call_needs_the_gateway_settings(tmp_path, monkeypatch):
    for key in asas_agent.GATEWAY_KEYS:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        cli.main(["one", str(tmp_path / "cv.docx"), "--profile-model", str(FIXTURES / "profile.yaml"), "--out", str(tmp_path / "out")])


def test_recheck_reads_saved_results_again_without_a_model(model, tmp_path, capsys):
    folder = tmp_path / "out" / "cv"
    write_outputs(built_profile(model), folder)
    assert {p.name for p in folder.iterdir()} == {"text.txt", "profile.json", "review.md"}
    assert cli.main(["recheck", "--profile-model", str(FIXTURES / "profile.yaml"), "--out", str(tmp_path / "out")]) == 0
    assert "cv:" in capsys.readouterr().out and (tmp_path / "out" / "summary.md").exists()
    assert (tmp_path / "out").stat().st_mode & 0o777 == 0o700  # personal data: the owner's only


def test_the_upload_page_reads_a_cv_and_keeps_the_run(model, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from asas_cv_profile import upload_router

    def answer(call, s):
        if s.name == "Name":
            return {"full_name": "Sara Example", "lines": [[1, 1]]}
        return None

    app = FastAPI()
    app.include_router(upload_router(ProfileBuilder(model, Scripted(model, answer)), tmp_path))
    client = TestClient(app)
    assert "<html" in client.get("/").text
    cv = docx("Sara Example", "Senior Data Analyst at Example Co since 2019, reporting for twelve departments across the group.",
              "Built the monthly reporting pipeline and trained the analysts who run it.")
    got = client.post("/api/parse", files={"file": ("cv.docx", cv)}, data={"as_of": "2026-10-28"})
    assert got.status_code == 200
    body = got.json()
    assert body["profile"]["Identity"]["Name"]["fields"]["Full name"]["check"] == "verified"
    assert client.get("/api/runs").json() == [{"run": body["run"]}]
    assert json.loads(client.get(f"/files/{body['run']}/profile.json").text)["file"] == "cv.docx"
    assert client.get("/files/../../etc/passwd").status_code == 404
    refused = client.post("/api/parse", files={"file": ("cv.docx", docx("Page 1"))})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "document_too_little_text"
