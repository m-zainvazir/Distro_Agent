export type DiscoveryStatus = 'idle' | 'loading' | 'complete' | 'error'

export interface StartDiscoveryRequest {
  brand_url: string
  location: string
  vertical_tag: string
}

export interface StartDiscoveryResponse {
  task_id: string
  status: 'processing'
}

export interface StatusResponse {
  status: 'processing' | 'complete' | 'error'
  progress: number
}

export interface StoreCandidate {
  name: string
  city: string
  state: string
  address: string
  storefront_image_urls: string[]
  price_tier: string | null
  instagram_handle: string | null
  website_url: string | null
}

export interface ScoredStore {
  store: StoreCandidate
  final_score: number
  outreach_priority: 'HIGH' | 'MEDIUM' | 'LOW'
  why_matched: string
  match_summary: string
  vision_was_run: boolean
}

export interface ReportResponse {
  stores: ScoredStore[]
  report_html: string
  errors: string[]
}
