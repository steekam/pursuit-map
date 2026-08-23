# PursuitMap Phase 0 glossary

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

- A tender is not an opportunity.
- A signal is not evidence.
- A raw buyer name is not a canonical Buyer.
- A raw supplier name is not a canonical Supplier.
