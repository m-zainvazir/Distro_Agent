import type { ReportResponse } from '@/lib/types'
import CTABanner from './CTABanner'
import StoreCard from './StoreCard'
import TeaserBlur from './TeaserBlur'

interface ResultsSectionProps {
  report: ReportResponse
  location: string
}

function emptyStateReason(errors: string[]): { title: string; detail: string } {
  const joined = errors.join(' ').toLowerCase()

  if (joined.includes('google maps') || joined.includes('api key') || joined.includes('places api')) {
    return {
      title: 'Store search could not run',
      detail:
        'The Google Maps lookup failed — the API key may be missing, disabled, or invalid. ' +
        'Check GOOGLE_MAPS_API_KEY in the backend .env and restart the worker.',
    }
  }
  if (joined.includes('scout')) {
    return {
      title: 'Store search was interrupted',
      detail: 'Something went wrong while searching for stores. Please try again in a moment.',
    }
  }
  if (errors.length > 0) {
    return {
      title: 'We hit a snag building your matches',
      detail: errors[0],
    }
  }
  return {
    title: 'No matches found',
    detail: "We couldn't find matching boutiques for this location. Try a larger or nearby city.",
  }
}

export default function ResultsSection({ report, location }: ResultsSectionProps) {
  const top5      = report.stores.slice(0, 5)
  const total     = report.stores.length
  const remaining = Math.max(0, total - 5)

  const brandDisplay = location ? `boutiques near ${location}` : 'boutiques in your area'
  const reason = emptyStateReason(report.errors ?? [])

  return (
    <section className="py-16 px-4">
      <div className="max-w-content mx-auto">

        {/* Header */}
        <div className="text-center mb-10">
          <h2
            className="font-display mb-3"
            style={{ fontSize: 32, fontWeight: 400 }}
          >
            Your Top Boutique Matches
          </h2>
          <p className="text-ink-muted">
            We found {total} {brandDisplay}.
            {top5.length > 0 && ' Here are the strongest fits for your brand.'}
          </p>
        </div>

        {/* Zero results state */}
        {top5.length === 0 ? (
          <div
            className="text-center p-10 rounded-xl border"
            style={{ borderColor: '#C4897A', background: '#FFF8F6' }}
          >
            <p className="text-blush font-medium mb-1">{reason.title}</p>
            <p className="text-ink-muted text-sm">{reason.detail}</p>
          </div>
        ) : (
          <>
            {/* Top 5 cards */}
            <div className="space-y-4">
              {top5.map((store, i) => (
                <StoreCard key={store.store.name + i} store={store} rank={i + 1} />
              ))}
            </div>

            {/* Teaser blur for remaining */}
            {remaining > 0 && <TeaserBlur remaining={remaining} />}

            {/* CTA */}
            <CTABanner totalStores={total} />
          </>
        )}
      </div>
    </section>
  )
}
