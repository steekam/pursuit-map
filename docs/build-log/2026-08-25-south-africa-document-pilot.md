# 2026-08-25 — South Africa document extraction pilot

## Source

- Source: South African National Treasury OCPO OCDS snapshot.
- Snapshot SHA-256: `a79b2ce7dccdd7f060d4d4745c1207693c2c5acb7a9fc8fdf9ddd578893d2a01`.
- Normalization run: `normalize-20260825T195426703850Z-a79b2ce7dccd`.
- Canonical document rows: 43,421.
- Documents with URLs: 41,760.

## Pilot

- Planned run: `documents-south-africa-20260825T195426703850Z`.
- Download limit: 25.
- Downloaded: 25.
- Download failures: 0.
- Unique response hashes: 25.
- Parser: Docling 2.121.0.
- OCR: disabled for the first pass.
- Parsed binaries: 24.
- Parse failures: 1 ZIP archive without a filename extension.

## Feature output

- Documents with observed features: 20.
- Documents with no observed features: 4.
- Evidence occurrences: 1,450.
- Evidence completeness: 1,445/1,450 (99.66%).
- Conflicts: 95.
- Ambiguities: 95.

Observed feature families include:

- software terms: 174 occurrences;
- specifications: 112;
- eligibility requirements: 110;
- ICT terms: 110;
- buyer contacts: 141;
- warranty periods: 62;
- quantities: 46;
- submission deadlines: 63;
- tender numbers: 76;
- required certifications: 32;
- networking terms: 25.

The pilot shows that South African documents can add scope, eligibility, timing, ICT, and commercial requirement evidence. The sample is too small to estimate source-wide coverage. ZIP expansion, OCR review, and a larger stratified sample remain open.

## Next test

1. Review the 4 no-feature documents and the ZIP failure.
2. Add archive expansion with preserved child-file provenance.
3. Select a stratified sample by document type, lifecycle stage, and procurement category.
4. Re-run the rules and measure field coverage against the canonical metadata.
5. Compare South African feature yield with the Kenya pilot under the same report contract.
