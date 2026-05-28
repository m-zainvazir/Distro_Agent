# Spec: Scout Agent

## Overview
Discovers physical retail stores that could carry the brand's products. Uses Google Maps Places API as primary source.

## State
class ScoutState(TypedDict):
    brand_profile: BrandProfile
    vertical_tag: str          # e.g., "aesthetic_beauty"
    target_location: str       # e.g., "Brooklyn, NY"
    max_stores: int            # default 50
    discovered_stores: list[StoreCandidate]
    errors: list[str]

## Nodes (LangGraph Graph Steps)
1. validate_inputs → check brand_profile and location are valid
2. generate_search_queries → Claude generates 5-10 search queries based on brand vibe
   Example queries: "aesthetic skincare boutique Brooklyn", "clean beauty salon NYC"
3. search_google_maps → run each query against Places API, deduplicate results
4. enrich_store_data → for each store, get website, hours, phone, category
5. initial_filter → remove chains (Sephora, Ulta), keep only indie boutiques
6. return_candidates → package as list of StoreCandidate objects

## Acceptance Criteria
- [ ] Returns at least 20 unique stores for any NYC/LA location
- [ ] Removes chain retailers correctly
- [ ] Handles Google Maps API rate limits with backoff
- [ ] All stores have place_id for deduplication
- [ ] Runs in < 45 seconds for 50 stores