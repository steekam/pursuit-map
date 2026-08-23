-- Run from the repository root with DuckDB after `normalize za`.

-- Procurement activity by buyer.
SELECT buyer_id, buyer_name, count(*) AS tender_count
FROM read_parquet('data/parquet/south_africa/tenders.parquet')
GROUP BY 1, 2
ORDER BY tender_count DESC, buyer_name;

-- Source category coverage and trend starting point.
SELECT main_procurement_category, count(*) AS tender_count
FROM read_parquet('data/parquet/south_africa/tenders.parquet')
GROUP BY 1
ORDER BY tender_count DESC;

-- Supplier activity by award rows.
SELECT supplier_id, supplier_name, count(*) AS award_count
FROM read_parquet('data/parquet/south_africa/award_suppliers.parquet')
GROUP BY 1, 2
ORDER BY award_count DESC, supplier_name;

-- Buyer-supplier relationship rows. A release may have a buyer and one or more suppliers.
SELECT
  a.buyer_id,
  a.buyer_name,
  s.supplier_id,
  s.supplier_name,
  count(*) AS award_count
FROM read_parquet('data/parquet/south_africa/awards.parquet') a
JOIN read_parquet('data/parquet/south_africa/award_suppliers.parquet') s
  USING (ocid, release_id, release_date, award_id)
GROUP BY 1, 2, 3, 4
ORDER BY award_count DESC, a.buyer_name, s.supplier_name;
