import json
from pathlib import Path


def test_pipeline_contract_declares_required_operations_and_boundaries():
    contract = json.loads((Path(__file__).parents[1] / "config" / "pipeline-contract.json").read_text(encoding="utf-8"))

    assert contract["contract_version"]
    assert contract["source"]["raw_artifact_immutable"] is True
    assert set(contract["layers"]) == {
        "raw_source_truth",
        "canonical_facts",
        "derived_observations",
        "intelligence_outputs",
    }
    assert set(contract["operations"]) == {"normalize", "verify", "profile", "enrich", "source-enrich", "materialize", "search"}
    assert all(operation["deterministic"] for operation in contract["operations"].values())
    assert contract["operations"]["search"]["evidence_required"] is True
    assert contract["boundaries"]["opaque_models"] is False
