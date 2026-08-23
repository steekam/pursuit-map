import json

from pursuitmap.source_enrichment import parse_tender_page, parse_tender_payload


def test_parse_tender_page_preserves_source_metadata():
    page = b"""
    <html><body>
      <div>OCID</div><div>ocds-5whusi-123-Test</div>
      <div>TENDER NUMBER</div><div>TEST/1/2025</div>
      <div>TITLE</div><div>Network modernization</div>
      <div>PROCUREMENT METHOD</div><div>Open Tender</div>
      <div>PROCUREMENT CATEGORY</div><div>Goods</div>
      <div>SUBMISSION METHODS</div><div>Electronic submission</div>
      <div>RESERVATION SCHEME</div><div>MSMEs</div>
      <div>OPENING VENUE</div><div>Boardroom</div>
      <div>PUBLISHED DATE</div><div>January 1st, 2025</div>
      <div>CLOSE DATE AND TIME</div><div>Jan 20th 2025 10:00</div>
      <div>TENDER FEE</div><div>0</div>
      <div>TENDER VALIDITY IN DAYS</div><div>90</div>
      <div>FINANCIAL YEAR</div><div>2024/2025</div>
      <div>PREFERENCE AND RESERVATION SCHEME</div><div>YES</div>
      <div>PUBLIC LINK</div><div>https://tenders.go.ke/tenders/123</div>
      <div>ATTACHMENTS</div><div>Tender Document</div><div>Test document</div>
      <a href="https://tenders.go.ke/storage/Documents/test.pdf">VIEW</a>
    </body></html>
    """
    result = parse_tender_page(page)
    assert result["ocid"] == "ocds-5whusi-123-Test"
    assert result["procurement_category"] == "Goods"
    assert result["close_date_raw"] == "Jan 20th 2025 10:00"
    assert "test.pdf" in result["attachments_json"]


def test_parse_tender_payload_uses_official_api_fields():
    payload = json.dumps({
        "ocid": "ocds-5whusi-123-Test", "tender_ref": "TEST/1/2025", "title": "Network modernization",
        "pe": {"id": 7, "name": "Buyer", "pin": "P000000000X"},
        "procurement_method": {"title": "Open Tender", "code": "open"},
        "procurement_category": {"title": "Goods", "code": "goods"},
        "submission_methods": [{"code": "electronic"}], "bidder_categories": [{"code": "msmes"}],
        "published_at": "2025-01-01 00:00:00", "close_at": "2025-01-20 10:00:00",
        "tender_fee": 0, "validity_in_days": 90, "financial_year": {"name": "2024/2025"},
        "documents": [{"id": 1, "url": "/storage/Documents/test.pdf"}],
    }).encode()
    result = parse_tender_payload(payload)
    assert result["procuring_entity_pin"] == "P000000000X"
    assert result["procurement_method_code"] == "open"
    assert result["tender_fee_raw"] == "0"
    assert "test.pdf" in result["attachments_json"]
