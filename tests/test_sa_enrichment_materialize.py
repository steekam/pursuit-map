from pursuitmap.sa_enrichment_materialize import _api_fields, _present


def test_presence_distinguishes_empty_json_text():
    assert not _present(None)
    assert not _present("")
    assert not _present("[]")
    assert not _present("{}")
    assert _present("value")
    assert _present(["value"])


def test_api_fields_map_nested_tender_values():
    fields = _api_fields({
        "parties": [{"name": "Buyer"}],
        "tender": {
            "province": "Gauteng",
            "deliveryLocation": "Pretoria",
            "contactPerson": {"name": "A"},
            "documents": [{"url": "https://example.test/doc.pdf"}],
        },
    })
    assert fields["province"] == "Gauteng"
    assert fields["delivery_location"] == "Pretoria"
    assert fields["contact_person"] == {"name": "A"}
    assert fields["parties"] == [{"name": "Buyer"}]
