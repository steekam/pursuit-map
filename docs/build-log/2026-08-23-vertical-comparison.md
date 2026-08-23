# 2026-08-23 — experimental vertical comparison

## Hypothesis

The deterministic, field-weighted retrieval design may transfer beyond ICT. Candidate volume and metadata sensitivity may differ by vertical.

## Work

Added versioned `construction` and `healthcare` taxonomies beside `ict`. Updated search to select a taxonomy. Updated evaluation to compare requested verticals across four metadata baselines.

## Measurement

Evaluation run: `evaluate-20260823T151201339648Z-a79b2ce7dccd`

| Vertical | Title only | Title + description | Title + description + category | Full metadata | Full-metadata buyers | Full-metadata suppliers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ICT | 286 | 4,775 | 4,575 | 7,529 | 569 | 1,258 |
| Construction | 13 | 3,783 | 5,678 | 5,826 | 459 | 1,008 |
| Healthcare | 3 | 264 | 255 | 264 | 75 | 78 |

Every included candidate had an evidence record in this evaluation. Full-metadata overlap with title-only was 272/286 for ICT, 13/13 for construction, and 3/3 for healthcare. Full-metadata overlap with title-plus-description was 4,359/4,775, 3,781/3,783, and 254/264.

## Observation

Construction has substantial category-driven expansion. Category metadata increases candidates from 3,783 to 5,678. Healthcare remains small after description matching. Category metadata adds little. ICT has the broadest candidate set and the largest supplier coverage.

These are retrieval counts. They do not measure precision, recall, market size, demand, or commercial likelihood. No reviewed gold set exists.

## Decision

Keep construction and healthcare as controlled experiments. Require a human-reviewed challenge set before promoting either taxonomy to a product vertical. The taxonomy interface supports comparative experiments.

## Next

Create a reviewed challenge set with positive, negative, and ambiguous records for all three verticals. Compare baseline overlap and error patterns before adding richer retrieval methods.

## Publication

private
