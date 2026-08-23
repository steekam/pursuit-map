# 2026-08-23 — experimental vertical comparison

## Hypothesis

The deterministic field-weighted retrieval design should transfer beyond ICT, but candidate volume and metadata sensitivity may differ by vertical.

## Work

Added versioned `construction` and `healthcare` taxonomies beside the existing `ict` taxonomy. Updated search to select the requested taxonomy and evaluation to compare all requested verticals across four metadata baselines.

## Measurement

Evaluation run: `evaluate-20260823T151201339648Z-a79b2ce7dccd`

| Vertical | Title only | Title + description | Title + description + category | Full metadata | Full-metadata buyers | Full-metadata suppliers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ICT | 286 | 4,775 | 4,575 | 7,529 | 569 | 1,258 |
| Construction | 13 | 3,783 | 5,678 | 5,826 | 459 | 1,008 |
| Healthcare | 3 | 264 | 255 | 264 | 75 | 78 |

All included candidates had evidence records in this evaluation output. Full-metadata overlap with title-only was 272/286 for ICT, 13/13 for construction, and 3/3 for healthcare. Full-metadata overlap with title-plus-description was 4,359/4,775, 3,781/3,783, and 254/264 respectively.

## Observation

Construction has substantial category-driven expansion: adding category metadata increases candidates from 3,783 to 5,678. Healthcare remains small and stable after description matching; category metadata adds little. ICT remains the broadest candidate set and has the largest supplier coverage.

These are retrieval counts, not precision, recall, market size, demand, or commercial likelihood. No reviewed gold set exists yet.

## Decision

Keep construction and healthcare as controlled experiments. Do not promote either to a product vertical until a human-reviewed challenge set tests false positives and evidence quality. The current taxonomy interface is suitable for comparative experiments.

## Next

Create a reviewed challenge set with positive, negative, and ambiguous records for all three verticals. Compare baseline overlap and error patterns before adding richer retrieval methods.

## Publication

private
