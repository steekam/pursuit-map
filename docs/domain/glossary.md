# PursuitMap domain glossary

The glossary uses terms from procurement, data engineering, information retrieval, and evaluation. Definitions are working definitions for the current phase.

## Procurement domain

| Term | Working definition | OCDS relationship |
| --- | --- | --- |
| Buyer | Public organization represented as the buyer in a contracting process. | `buyer`; sometimes supported by `parties`. |
| Supplier | Organization named as supplier of an award. | `awards[].suppliers[]`. |
| Procurement plan | Early statement of intended procurement activity. | `planning`; optional `planning.items[]`. |
| Procurement plan item | A planned procurement line with description, classification, period, or value. | `planning.items[]` when published. |
| Tender | The solicitation stage and its details. | `tender`. |
| Award | Decision assigning a tender or lot to a supplier. | `awards[]`. |
| Contract | Formal contracting stage after an award. | `contracts[]`. |
| Category | Source classification or procurement category. | `classification`, `mainProcurementCategory`, and item fields. |
| Capability | PursuitMap's later seller-oriented concept, such as networking or cybersecurity. | Derived; not assumed to equal an OCDS category. |
| Signal | A derived observation that may indicate commercial relevance or timing. | Derived from plans, tenders, awards, contracts, and history. |
| Evidence | A source-backed fact supporting a signal or opportunity. | Source fields and document URLs. |
| Opportunity | A qualified, derived buyer/capability hypothesis. | Not an OCDS object; defer until later phases. |

Important distinctions:

- A tender records a solicitation. An opportunity is derived from evidence and signals.
- A signal is a derived observation. Evidence is a source-backed fact.
- A raw buyer name is a source value. A canonical Buyer is an identity observation with source context.
- A raw supplier name is a source value. A canonical Supplier is an identity observation with source context.

## Data and evidence

| Term | Working definition |
| --- | --- |
| Raw source truth | The source artifact and values preserved without interpretation. |
| Canonical fact | A direct mapping from a source field into a stable table field. |
| Derived observation | A deterministic value calculated from canonical facts. |
| Intelligence output | A ranked result, signal, or explanation produced from derived observations. |
| Provenance | Information that identifies the source snapshot, record, field path, transformation, and run. |
| Snapshot | A specific source artifact identified by its SHA-256 hash. |
| Gold set | A dataset reviewed by people and used as the reference for evaluation. |
| Evidence completeness | The share of results that include the required source references. |

## Retrieval and classification

| Term | Working definition |
| --- | --- |
| Query | The user's text request used to select or rank records. |
| Candidate | A record that passes the retrieval inclusion rules. |
| Retrieval | The process that selects records relevant to a query or vertical. |
| Ranking | The ordered presentation of retrieved records. |
| Baseline | A simple method used as a reference for comparison. |
| Taxonomy | A versioned set of categories, terms, weights, and exclusions. |
| Field weight | The value that controls how strongly a matched field affects a rule score. |
| Rule score | A deterministic number calculated from configured matches and weights. The score has no probability meaning. |
| Exclusion | An explicit rule that removes a record or category from the result set. |
| Candidate coverage | The number or share of relevant records that a retrieval method returns. The measure becomes recall only with a reviewed gold set. |
| Result overlap | The number of records shared by two result sets. |

## Evaluation

For classification evaluation, define the positive class before calculating a metric. In retrieval, define the reviewed relevant set first.

| Term | Working definition |
| --- | --- |
| True positive (TP) | A record marked relevant by the system and relevant in the reviewed reference. |
| False positive (FP) | A record marked relevant by the system and not relevant in the reviewed reference. |
| False negative (FN) | A record not returned by the system and relevant in the reviewed reference. |
| True negative (TN) | A record not returned by the system and not relevant in the reviewed reference. |
| Precision | `TP / (TP + FP)`. Of the returned positive records, the share that is relevant. |
| Recall | `TP / (TP + FN)`. Of the relevant reference records, the share that was returned. |
| Accuracy | `(TP + TN) / (TP + FP + FN + TN)`. The share of all decisions that is correct. It can mislead when one class is much larger. |
| F1 score | The harmonic mean of precision and recall: `2 × precision × recall / (precision + recall)`. |
| Specificity | `TN / (TN + FP)`. Of the non-relevant reference records, the share correctly rejected. |
| Support | The number of reference records in a class or evaluation slice. |
| Prevalence | The share of reference records that belong to the positive class. |
| Threshold | A rule-score or probability boundary used to decide inclusion. |
| Ranking metric | A metric that evaluates the order of results, such as reciprocal rank or discounted cumulative gain. |
| Mean reciprocal rank (MRR) | The mean of the reciprocal rank of the first relevant result for each query. |
| Normalized discounted cumulative gain (nDCG) | A ranking metric that gives more credit when relevant results appear near the top. |

Precision, recall, accuracy, F1, MRR, and nDCG require a reviewed reference. Candidate counts and result overlap alone do not establish retrieval quality.

## Interpretation rules

- A score is a deterministic retrieval value unless a reviewed evaluation defines another meaning.
- A high recall result can contain many false positives.
- A high precision result can miss many relevant records.
- Accuracy can look high when the negative class dominates.
- A metric without its positive class, support, time window, and gold-set version is incomplete.
