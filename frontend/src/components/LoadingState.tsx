interface LoadingStateProps {
  progress: number
  currentStep: string
  location: string
}

export default function LoadingState({ progress, currentStep, location }: LoadingStateProps) {
  return (
    <section className="py-20 px-4">
      <div className="max-w-content mx-auto flex flex-col items-center gap-8">

        {/* Botanical ring */}
        <div className="relative flex items-center justify-center">
          <div
            className="animate-spin-slow"
            style={{
              width: 120,
              height: 120,
              borderRadius: '50%',
              border: '3px solid #E8F0E9',
              borderTopColor: '#C4897A',
            }}
          />
          <span
            className="absolute font-display text-2xl text-sage"
            style={{ fontStyle: 'italic' }}
          >
            D
          </span>
        </div>

        {/* Heading */}
        <p className="font-display text-xl text-ink text-center" style={{ fontStyle: 'italic' }}>
          Analyzing your brand
        </p>

        {/* Progress message — fades between steps */}
        <p
          key={currentStep}
          className="animate-fade-in font-display text-2xl text-ink text-center"
          style={{ fontStyle: 'italic', minHeight: '2rem' }}
        >
          {currentStep}
        </p>

        {/* Progress bar */}
        <div className="w-full max-w-sm">
          <div
            className="w-full h-1 rounded-full overflow-hidden"
            style={{ backgroundColor: '#E8F0E9' }}
          >
            <div
              className="h-full bg-sage rounded-full transition-all duration-500 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-center text-ink-muted text-sm mt-2">{progress}%</p>
        </div>

        {/* Location sub-text */}
        {location && (
          <p className="text-ink-muted text-sm">
            Scanning boutiques in {location}
          </p>
        )}
      </div>
    </section>
  )
}
