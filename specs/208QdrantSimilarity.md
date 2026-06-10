# Spec: Block I — Qdrant Similarity Search + Store Dedup

## Overview
Read the brand embeddings already stored in Qdrant. Add similar-brand search and cross-run store deduplication.

## Files to create / edit
| File | Purpose |
|---|---|
| app/services/similarity_service.py | find_similar_brands + dedup helpers |
| app/api/v1/insights.py | "brands like yours" endpoint |
| tests/services/test_similarity.py | Cosine search tests |

## Functions
async find_similar_brands(tenant_id, brand_id, k=5) -> list[SimilarBrand]
   → Cosine search on brand_embeddings collection in Qdrant
   → Returns top-k OTHER brands (exclude self, respect tenant privacy:
     return anonymized aggregate, not competitor PII)

async dedup_stores(tenant_id, candidates) -> list[StoreCandidate]
   → Before scoring, drop stores already scored/emailed for this tenant
   → Match on google_place_id against existing StoreCandidate rows

## Privacy Rule
Cross-brand insights are ANONYMIZED aggregates only. Never expose one tenant's
specific store list or contacts to another tenant.

## Acceptance Criteria
- [x] similarity_service.py — find_similar_brands (cosine, excludes self)
- [x] dedup_stores removes already-processed place_ids
- [x] Cross-tenant insights anonymized — no PII leakage (test)
- [x] Analyst pipeline calls dedup before scoring
- [x] /api/v1/insights endpoint returns 'brands like yours'
