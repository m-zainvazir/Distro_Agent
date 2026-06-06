'use client'

import { useState } from 'react'

interface HeroSectionProps {
  onSubmit: (brandUrl: string, location: string, vertical: string) => void
  isLoading: boolean
}

const VERTICALS: { value: string; label: string }[] = [
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

export default function HeroSection({ onSubmit, isLoading }: HeroSectionProps) {
  const [brandUrl, setBrandUrl]   = useState('')
  const [location, setLocation]   = useState('')
  const [vertical, setVertical]   = useState(VERTICALS[0].value)
  const [urlError, setUrlError]   = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!brandUrl.startsWith('http')) {
      setUrlError('Please enter a full URL starting with https://')
      return
    }
    setUrlError('')
    onSubmit(brandUrl.trim(), location.trim(), vertical)
  }

  return (
    <section className="py-20 px-4">
      <div className="max-w-content mx-auto">

        {/* Top label */}
        <div className="flex items-center justify-center gap-3 mb-10">
          <span className="block w-10 h-px bg-sage opacity-50" />
          <span className="text-sage text-xs font-medium tracking-widest uppercase">
            Wholesale Distribution · Powered by AI
          </span>
          <span className="block w-10 h-px bg-sage opacity-50" />
        </div>

        {/* Headline */}
        <h1
          className="font-display text-center mb-6 leading-tight"
          style={{ fontSize: 'clamp(36px, 5vw, 56px)', fontWeight: 400 }}
        >
          Drop Your Shopify URL.{' '}
          <br className="hidden sm:block" />
          See Which Boutiques
          <br />
          Will Love You.
        </h1>

        {/* Subheadline */}
        <p className="text-center text-ink-muted text-lg leading-relaxed mb-10 max-w-lg mx-auto">
          Paste your store link below. In 60 seconds, our AI analyzes your brand
          aesthetic and finds the physical boutiques most likely to carry — and
          sell — your products.
        </p>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-3">
          {/* URL input */}
          <div>
            <input
              type="text"
              value={brandUrl}
              onChange={e => { setBrandUrl(e.target.value); setUrlError('') }}
              placeholder="https://yourbrand.myshopify.com or etsy.com/shop/yourshop"
              disabled={isLoading}
              className="w-full px-4 text-base bg-surface border border-border rounded-sm
                         transition-all duration-150 disabled:opacity-60 disabled:cursor-not-allowed
                         focus:outline-none focus:border-sage"
              style={{
                height: '56px',
                boxShadow: urlError ? '0 0 0 3px rgba(196,137,122,0.15)' : undefined,
              }}
              onFocus={e => {
                if (!urlError) {
                  e.currentTarget.style.boxShadow = '0 0 0 3px rgba(124,154,130,0.15)'
                  e.currentTarget.style.borderColor = '#7C9A82'
                }
              }}
              onBlur={e => {
                e.currentTarget.style.boxShadow = ''
                if (!urlError) e.currentTarget.style.borderColor = ''
              }}
            />
            {urlError && (
              <p className="mt-1.5 text-sm text-blush">{urlError}</p>
            )}
          </div>

          {/* Location input */}
          <input
            type="text"
            value={location}
            onChange={e => setLocation(e.target.value)}
            placeholder="City, State (optional — e.g. Brooklyn, NY)"
            disabled={isLoading}
            className="w-full px-4 h-12 text-sm bg-surface border border-border rounded-sm
                       transition-all duration-150 disabled:opacity-60 disabled:cursor-not-allowed
                       focus:outline-none focus:border-sage"
            onFocus={e => {
              e.currentTarget.style.boxShadow = '0 0 0 3px rgba(124,154,130,0.15)'
              e.currentTarget.style.borderColor = '#7C9A82'
            }}
            onBlur={e => {
              e.currentTarget.style.boxShadow = ''
              e.currentTarget.style.borderColor = ''
            }}
          />

          {/* Vertical / category select */}
          <select
            value={vertical}
            onChange={e => setVertical(e.target.value)}
            disabled={isLoading}
            aria-label="Product category"
            className="w-full px-4 h-12 text-sm bg-surface border border-border rounded-sm
                       transition-all duration-150 disabled:opacity-60 disabled:cursor-not-allowed
                       focus:outline-none focus:border-sage cursor-pointer text-ink"
          >
            {VERTICALS.map(v => (
              <option key={v.value} value={v.value}>{v.label}</option>
            ))}
          </select>

          {/* Submit button */}
          <button
            type="submit"
            disabled={isLoading}
            className="w-full h-[52px] bg-sage text-white text-base font-medium rounded-sm
                       transition-colors duration-150 cursor-pointer
                       hover:bg-sage-dark
                       disabled:opacity-60 disabled:cursor-not-allowed
                       flex items-center justify-center gap-2"
          >
            {isLoading ? (
              <>
                <span
                  className="inline-block w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"
                />
                Finding your matches...
              </>
            ) : (
              'Get My Free Report →'
            )}
          </button>
        </form>

        {/* Trust line */}
        <p className="text-center text-ink-muted text-sm mt-4">
          ✦ Free · No account needed · Results in ~60 seconds
        </p>
      </div>
    </section>
  )
}
