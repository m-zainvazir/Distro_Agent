import type { ReportResponse } from '../lib/types'
import CTABanner from './CTABanner'
import StoreCard from './StoreCard'
import TeaserBlur from './TeaserBlur'

interface ResultsSectionProps {
  report: ReportResponse
  location: string
}

function emptyStateReason(errors: string[]): { title: string; detail: string } {
  const joined = errors.join(' ').toLowerCase()

  // Find the raw Google error line so we can surface the actual status code
  const googleError = errors.find(
    e => e.toLowerCase().includes('google maps') || e.toLowerCase().includes('http ')
  )

  if (joined.includes('google maps') || joined.includes('api key') || joined.includes('places api')) {
    return {
      title: 'Store search could not run',
      detail: googleError
        ? `Google Maps error: ${googleError}`
        : 'The Google Maps lookup failed — check that GOOGLE_MAPS_API_KEY is set and that "Places API (New)" is enabled in Google Cloud Console.',
    }
  }
  if (joined.includes('scout')) {
    return {
      title: 'Store search was interrupted',
      detail: errors.find(e => e.toLowerCase().includes('scout')) ?? errors[0] ?? 'Unknown scout error.',
    }
  }
  if (errors.length > 0) {
    return {
      title: 'We hit a snag building your matches',
      detail: errors.join(' | '),
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
            {report.errors && report.errors.length > 0 && (
              <details className="mt-4 text-left">
                <summary className="text-xs text-ink-muted cursor-pointer select-none">
                  Show full error log ({report.errors.length})
                </summary>
                <pre className="mt-2 text-xs text-ink-muted whitespace-pre-wrap break-all bg-white rounded p-3 border border-border">
                  {report.errors.join('\n')}
                </pre>
              </details>
            )}
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
