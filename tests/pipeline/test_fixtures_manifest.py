import json
from pathlib import Path


def test_fixture_manifest_paths_exist() -> None:
    project_root = Path(__file__).resolve().parents[2]
    manifest_path = project_root / "tests" / "pipeline" / "fixtures" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "1.0"
    assert len(payload["fixtures"]) >= 4
    for fixture in payload["fixtures"]:
        assert (project_root / fixture["path"]).exists(), fixture["path"]
        assert fixture["source"] == "generated"
        assert fixture["third_party_material"] is False
