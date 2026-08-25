# 2026-08-26 — South Africa document analysis

## Scope

- Source snapshot: `a79b2ce7dccdd7f060d4d4745c1207693c2c5acb7a9fc8fdf9ddd578893d2a01`.
- Normalization run: `normalize-20260825T195426703850Z-a79b2ce7dccd`.
- Document pilot: 25 source binaries.
- Parsed units after ZIP expansion: 29.
- Parser: Docling `2.121.0`.
- OCR: disabled.

## ZIP handling

One ZIP response contained five PDF members. The parser now:

1. extracts supported members into a content-addressed staging directory;
2. rejects unsafe archive paths;
3. records unsupported members;
4. writes a child input manifest;
5. preserves the parent response hash and archive member name;
6. parses each child once.

The pilot produced 29 parsed units and zero unparsed source binaries.

## Document features

The rule layer produced 1,573 occurrences across 29 parsed units.

- Evidence complete: 1,568/1,573 (99.68%).
- Documents with observed features: 25.
- Documents without observed features: 4.
- Conflicts: 111.
- Ambiguities: 111.

The pilot exposed scope, eligibility, timing, identity, ICT, and commercial fields. The strongest feature counts were software terms (203), buyer contacts (147), specifications (120), eligibility requirements (115), ICT terms (132), and warranty periods (70).

The rule layer observed two cloud terms and no cybersecurity terms. This result measures the pilot and rule vocabulary. It does not show that the full SA source lacks cybersecurity content.

## Sol high classification

GPT-5.6 Sol with high reasoning classified 29 units in five JSONL batches.

| Role | Count |
| --- | ---: |
| Tender notice | 5 |
| Tender document | 5 |
| Financial proposal | 3 |
| RFP | 3 |
| Form | 4 |
| Addendum | 1 |
| Contract | 1 |
| Evaluation record | 1 |
| Meeting minutes | 1 |
| Unknown | 5 |

Confidence was high for 24 units, medium for 1, and low for 4. Thirteen units were marked as likely standard templates. These labels are observations and require human review before they become ground truth.

The deterministic TF-IDF analysis produced 21 similarity clusters and 13 edges at cosine threshold `0.45`.

- Tender documents had mean within-role similarity `0.352` across 5 units.
- RFPs had mean within-role similarity `0.223` across 3 units.
- Tender notices had mean within-role similarity `0.091` across 5 units.
- Financial proposals had mean within-role similarity `0.064` across 3 units.

The sample supports role-conditioned rules. Tender documents can carry technical, eligibility, timing, and commercial fields. Notices are better for identity, deadlines, and submission instructions. Financial proposals expose quantities, units, lots, and prices. Image-only documents need OCR or visual review.

## Capability assessment against the original goal

### Supported now

- Evidence-backed procurement discovery across 37,894 tenders.
- Historical descriptive analysis from February 2017 to August 2026.
- Buyer, supplier, award, contract, category, timing, and document metadata analysis.
- Deterministic ICT retrieval using title, description, category, and document metadata.
- Evidence-backed document observations with page or table references.
- Rule-based extraction of technical scope, eligibility, deadlines, and commercial requirements for captured documents.

### Partly supported

- ICT qualification can now use document terms when documents are acquired and parsed.
- Historical contract analysis remains useful, but the snapshot has only 1,653 contracts and no award dates.
- Document-derived timing can improve tender timing records, but conflicts and ambiguity remain visible.
- Supplier relationship analysis remains limited by 4,326 supplier rows with source supplier ID `0`.

### Unsupported or unsafe to claim

- Future demand prediction.
- Supplier quality or commercial likelihood.
- Market share or causal claims.
- Complete procurement plans. The snapshot has 37,894 planning objects and zero plan items.
- Reliable cybersecurity coverage from the current rule vocabulary.
- Source-wide document feature coverage from a 29-unit pilot.

## Decision

SA is a strong source for a descriptive procurement explorer and evidence-backed retrieval. The document layer can add qualification context. The current evidence does not support a predictive opportunity product.

Next work should expand the SA sample by document type and lifecycle stage, review the five low-confidence units, test OCR on image-only documents, and add role-conditioned rule profiles before wider document acquisition.
