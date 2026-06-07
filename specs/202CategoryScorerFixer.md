# Spec: Block B — Category Scorer Fix

## Overview
Fix the vocabulary mismatch between Google place types and brand keywords. Implement both a quick curated map AND the better embedding-based approach, with the embedding approach as primary and the map as fallback.

## Problem
Google: "cosmetics_store" | Brand: "makeup", "lip care" → 0 overlap → wrong score

## Solution 1 (Fallback): Curated Type Map
File: app/tools/category_map.py
A dict mapping Google place types to consumer terms:
  "cosmetics_store" → ["makeup", "beauty", "skincare", "fragrance", "cosmetics"]
  "beauty_salon"    → ["beauty", "skincare", "spa", "salon"]
  "shoe_store"      → ["footwear", "shoes", "sneakers"]
  "clothing_store"  → ["apparel", "clothing", "fashion"]
  "gift_shop"       → ["gifts", "home", "accessories", "lifestyle"]
  ... (cover the top 30 retail place types)

## Solution 2 (Primary): Embedding-Based Matching
File: app/tools/category_scorer.py (rewrite)
- We already compute brand embeddings (Qdrant) in Phase 1
- Embed the store's combined "categories + name + review snippets" text
- Compute cosine similarity to the brand's embedding
- Map similarity 0.0-1.0 to a 0-10 category score:
    sim > 0.55 → 9-10 | 0.45-0.55 → 7-8.9 | 0.35-0.45 → 5-6.9 |
    0.25-0.35 → 3-4.9 | < 0.25 → 1-2.9
- If embedding call fails → fall back to curated-map keyword overlap

## Acceptance Criteria
- [ ] A cosmetics_store scores >= 7.0 category for a beauty brand
- [ ] A shoe_store scores < 4.0 category for a beauty brand
- [ ] Embedding failure falls back to the curated map without crashing
- [ ] Existing analyst tests still pass with new scorer
