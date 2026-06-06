'use client'

import { useState } from 'react'
import HeroSection from '@/components/HeroSection'
import LoadingState from '@/components/LoadingState'
import ResultsSection from '@/components/ResultsSection'
import { useDiscovery } from '@/hooks/useDiscovery'

export default function Home() {
  const { status, progress, currentStep, report, error, startDiscovery, reset } =
    useDiscovery()
  const [location, setLocation] = useState('')

  function handleSubmit(brandUrl: string, loc: string, vertical: string) {
    setLocation(loc)
    startDiscovery(brandUrl, loc, vertical)
  }

  return (
    <main className="min-h-screen bg-bg">
      {/* Idle / error → show hero */}
      {(status === 'idle' || status === 'error') && (
        <>
          <HeroSection
            onSubmit={handleSubmit}
            isLoading={false}
          />
          {error && (
            <div className="max-w-content mx-auto px-4 -mt-4 pb-10">
              <div
                className="rounded-lg px-4 py-3 text-sm flex items-start gap-3"
                style={{ background: '#FFF8F6', borderLeft: '3px solid #C4897A' }}
              >
                <span className="text-blush mt-0.5">⚠</span>
                <div>
                  <p className="text-ink font-medium mb-0.5">Something went wrong</p>
                  <p className="text-ink-muted">{error}</p>
                  <button
                    onClick={reset}
                    className="mt-2 text-sage text-sm underline underline-offset-2"
                  >
                    Try again
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* Loading */}
      {status === 'loading' && (
        <LoadingState
          progress={progress}
          currentStep={currentStep}
          location={location}
        />
      )}

      {/* Complete */}
      {status === 'complete' && report && (
        <>
          <div className="max-w-content mx-auto px-4 pt-10 flex justify-end">
            <button
              onClick={reset}
              className="text-sm text-ink-muted hover:text-ink underline underline-offset-2 transition-colors"
            >
              ← Start over
            </button>
          </div>
          <ResultsSection report={report} location={location} />
        </>
      )}
    </main>
  )
}
