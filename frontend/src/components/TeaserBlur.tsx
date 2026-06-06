interface TeaserBlurProps {
  remaining: number
}

const TEASER_STORES = [
  { name: '████████ Studio',  city: '██████', score: 88, opacity: 0.7 },
  { name: '████████ & Co.',   city: '██████', score: 84, opacity: 0.5 },
  { name: 'The ████████',    city: '██████', score: 81, opacity: 0.3 },
]

export default function TeaserBlur({ remaining }: TeaserBlurProps) {
  return (
    <div className="relative mt-4" style={{ overflow: 'hidden' }}>
      {/* Blurred fake cards */}
      <div
        className="space-y-3"
        style={{ filter: 'blur(6px)', pointerEvents: 'none', userSelect: 'none' }}
      >
        {TEASER_STORES.map((s, i) => (
          <div
            key={i}
            className="bg-surface border border-border rounded-xl p-6"
            style={{ opacity: s.opacity }}
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="font-medium text-ink">{s.name}</p>
                <p className="text-sm text-ink-muted">{s.city}, NY</p>
              </div>
              <span
                className="px-3 py-1 rounded-full text-sm font-semibold"
                style={{ backgroundColor: '#E8F0E9', color: '#4A6B50' }}
              >
                {s.score}% match
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Fade overlay */}
      <div
        className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center px-6"
        style={{
          background:
            'linear-gradient(to bottom, rgba(250,250,248,0) 0%, rgba(250,250,248,0.97) 40%)',
        }}
      >
        <div className="mt-16">
          {/* Lock icon */}
          <svg
            className="mx-auto mb-3 text-ink-muted"
            width="24" height="24" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" strokeWidth="2"
          >
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>

          <p className="font-display text-2xl text-ink mb-2" style={{ fontWeight: 400 }}>
            +{remaining} more boutiques in your report
          </p>
          <p className="text-ink-muted text-sm leading-relaxed max-w-xs mx-auto">
            Unlock your full report to see every match, complete contact details,
            and draft outreach emails.
          </p>
        </div>
      </div>
    </div>
  )
}
