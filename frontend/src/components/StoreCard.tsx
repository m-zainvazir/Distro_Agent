import type { ScoredStore } from '../lib/types'

interface StoreCardProps {
  store: ScoredStore
  rank: number
}

const PRIORITY_STYLES = {
  HIGH:   { bg: '#F5EAE7', color: '#C4897A' },
  MEDIUM: { bg: '#E8F0E9', color: '#4A6B50' },
  LOW:    { bg: '#F5F5F5', color: '#6B6B6B' },
}

export default function StoreCard({ store, rank }: StoreCardProps) {
  const pct = Math.round(store.final_score * 10)
  const priority = PRIORITY_STYLES[store.outreach_priority] ?? PRIORITY_STYLES.LOW
  const delayMs = (rank - 1) * 100

  return (
    <div
      className="animate-fade-up relative bg-surface border border-border rounded-xl p-6
                 shadow-[0_1px_3px_rgba(0,0,0,0.06)]
                 hover:shadow-[0_4px_16px_rgba(0,0,0,0.08)] hover:border-sage-light
                 transition-all duration-200 cursor-default"
      style={{ animationDelay: `${delayMs}ms`, opacity: 0 }}
    >
      {/* Rank — large decorative number */}
      <span
        className="absolute top-4 left-4 font-display leading-none select-none pointer-events-none"
        style={{ fontSize: 48, fontWeight: 400, color: '#E8E4DF' }}
        aria-hidden
      >
        {String(rank).padStart(2, '0')}
      </span>

      {/* Header row */}
      <div className="flex items-start justify-between gap-4 pl-14">
        <div>
          {store.store.website_url ? (
            <a
              href={store.store.website_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-base font-medium text-ink hover:text-sage underline-offset-2 hover:underline transition-colors"
            >
              {store.store.name}
            </a>
          ) : (
            <h3 className="text-base font-medium text-ink">{store.store.name}</h3>
          )}
          <p className="text-sm text-ink-muted mt-0.5">
            {store.store.city}, {store.store.state}
          </p>
          {(store.store.website_url || store.store.instagram_handle) && (
            <div className="flex items-center gap-3 mt-1.5">
              {store.store.website_url && (
                <a
                  href={store.store.website_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-sage hover:text-sage-dark underline underline-offset-2"
                >
                  Visit website ↗
                </a>
              )}
              {store.store.instagram_handle && (
                <a
                  href={`https://instagram.com/${store.store.instagram_handle.replace('@', '')}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-sage hover:text-sage-dark underline underline-offset-2"
                >
                  Instagram ↗
                </a>
              )}
            </div>
          )}
        </div>

        {/* Score badge */}
        <span
          className="shrink-0 px-3 py-1 rounded-full text-sm font-semibold"
          style={{ backgroundColor: '#E8F0E9', color: '#4A6B50' }}
        >
          {pct}% match
        </span>
      </div>

      {/* Divider */}
      <hr className="my-4 border-border" />

      {/* Why this store */}
      <div
        className="pl-3"
        style={{ borderLeft: '2px solid #E8F0E9' }}
      >
        <p
          className="text-xs font-medium text-ink-muted uppercase tracking-widest mb-1.5"
          style={{ letterSpacing: '0.08em' }}
        >
          Why this store?
        </p>
        <p className="text-sm text-ink-muted leading-relaxed">
          {store.why_matched}
        </p>
      </div>

      {/* Priority badge */}
      <div className="flex justify-end mt-4">
        <span
          className="px-2.5 py-1 rounded-full text-xs font-medium uppercase tracking-wider"
          style={{
            backgroundColor: priority.bg,
            color: priority.color,
            letterSpacing: '0.08em',
          }}
        >
          {store.outreach_priority}
        </span>
      </div>
    </div>
  )
}
