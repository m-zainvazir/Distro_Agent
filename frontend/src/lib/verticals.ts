// Vertical configuration — single source for the generic category dropdown and
// the verticalized "wedge" landing experience served on niche subdomains
// (e.g. beauty.distroagent.ai). Mirrors the backend Context Router verticals.

export interface VerticalOption {
  value: string
  label: string
}

// Options shown in the generic (apex-domain) category dropdown.
export const VERTICALS: VerticalOption[] = [
  { value: 'aesthetic_beauty', label: 'Beauty & Cosmetics' },
  { value: 'skincare', label: 'Skincare' },
  { value: 'apparel', label: 'Apparel & Fashion' },
  { value: 'footwear', label: 'Footwear' },
  { value: 'home_goods', label: 'Home & Decor' },
  { value: 'jewelry', label: 'Jewelry & Accessories' },
  { value: 'food_beverage', label: 'Food & Beverage' },
  { value: 'wellness', label: 'Wellness' },
  { value: 'pet_products', label: 'Pet Products' },
]

// A vertical "wedge" — the niche-specific landing copy + the hidden industry tag
// injected into the discovery request when served on that vertical's subdomain.
export interface VerticalWedge {
  value: string          // vertical_tag sent to the backend (Context Router key)
  eyebrow: string
  headline: string
  subheadline: string
  urlPlaceholder: string
}

export const WEDGES: Record<string, VerticalWedge> = {
  aesthetic_beauty: {
    value: 'aesthetic_beauty',
    eyebrow: 'For Indie Beauty & Skincare Founders',
    headline: 'Drop Your Shopify URL. See Which Clean-Beauty Boutiques Will Love You.',
    subheadline:
      'Paste your store link below. In 60 seconds our AI reads your formulations, ' +
      'ingredients, and aesthetic — then finds the boutiques, spas, and apothecaries ' +
      'most likely to stock and sell your line.',
    urlPlaceholder: 'https://yourbeautybrand.com',
  },
  wellness: {
    value: 'wellness',
    eyebrow: 'For Health & Wellness Founders',
    headline: 'Drop Your Store URL. See Which Wellness Studios Will Stock You.',
    subheadline:
      'Paste your store link below. In 60 seconds our AI reads your certifications, ' +
      'actives, and positioning — then finds the wellness studios, health-food stores, ' +
      'and spa counters most likely to carry your products.',
    urlPlaceholder: 'https://yourwellnessbrand.com',
  },
  fashion: {
    value: 'fashion',
    eyebrow: 'For Independent Fashion Founders',
    headline: 'Drop Your Store URL. See Which Boutiques Will Carry Your Label.',
    subheadline:
      'Paste your store link below. In 60 seconds our AI reads your aesthetic, ' +
      'materials, and positioning — then finds the indie fashion boutiques and concept ' +
      'stores most likely to stock and sell your label.',
    urlPlaceholder: 'https://yourfashionbrand.com',
  },
  home_goods: {
    value: 'home_goods',
    eyebrow: 'For Home & Lifestyle Founders',
    headline: 'Drop Your Store URL. See Which Boutiques Will Love Your Pieces.',
    subheadline:
      'Paste your store link below. In 60 seconds our AI reads your craftsmanship, ' +
      'materials, and design story — then finds the home-decor boutiques, design ' +
      'studios, and gift shops most likely to carry your pieces.',
    urlPlaceholder: 'https://yourhomebrand.com',
  },
  food_beverage: {
    value: 'food_beverage',
    eyebrow: 'For Food & Beverage Founders',
    headline: 'Drop Your Store URL. See Which Grocers Will Put You on the Shelf.',
    subheadline:
      'Paste your store link below. In 60 seconds our AI reads your certifications, ' +
      'dietary profile, and sourcing — then finds the specialty grocers, gourmet shops, ' +
      'and cafes most likely to stock your products.',
    urlPlaceholder: 'https://yourfoodbrand.com',
  },
}

// Subdomain label → canonical wedge key. Aliases let several subdomains resolve
// to one vertical (e.g. skincare. → aesthetic_beauty).
const SUBDOMAIN_TO_VERTICAL: Record<string, string> = {
  beauty: 'aesthetic_beauty',
  skincare: 'aesthetic_beauty',
  cosmetics: 'aesthetic_beauty',
  wellness: 'wellness',
  health: 'wellness',
  fashion: 'fashion',
  apparel: 'fashion',
  home: 'home_goods',
  decor: 'home_goods',
  food: 'food_beverage',
  beverage: 'food_beverage',
}

// Hosts that are never a vertical subdomain (apex, www, app, api, local, previews).
const NON_VERTICAL_HOSTS = new Set([
  'www',
  'distroagent',
  'app',
  'api',
  'localhost',
  '127',
])

/**
 * Resolve the active wedge from the hostname (and an optional `?v=` override for
 * local testing). Returns null on the generic apex domain or unknown subdomains.
 */
export function resolveWedge(hostname: string, search = ''): VerticalWedge | null {
  const override = new URLSearchParams(search).get('v')
  if (override) {
    const key = override.toLowerCase()
    return WEDGES[SUBDOMAIN_TO_VERTICAL[key] ?? key] ?? null
  }

  const sub = hostname.toLowerCase().split(':')[0].split('.')[0]
  if (!sub || NON_VERTICAL_HOSTS.has(sub)) return null

  const tag = SUBDOMAIN_TO_VERTICAL[sub]
  return tag ? WEDGES[tag] ?? null : null
}
