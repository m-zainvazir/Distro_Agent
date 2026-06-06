'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchReport,
  pollStatus,
  startDiscovery as apiStart,
} from '@/lib/api'
import type { DiscoveryStatus, ReportResponse } from '@/lib/types'

const PROGRESS_MESSAGES: Record<number, string> = {
  0:  'Reading your brand story...',
  15: 'Analyzing your aesthetic and color palette...',
  30: 'Scanning 200+ boutiques in your area...',
  50: 'Matching your vibe to physical storefronts...',
  70: 'Scoring brand-to-shelf fit for top matches...',
  85: 'Generating your personalized match report...',
  95: 'Almost ready...',
}

function getProgressMessage(progress: number): string {
  const thresholds = [95, 85, 70, 50, 30, 15, 0] as const
  for (const t of thresholds) {
    if (progress >= t) return PROGRESS_MESSAGES[t]
  }
  return PROGRESS_MESSAGES[0]
}

export interface UseDiscoveryReturn {
  status: DiscoveryStatus
  progress: number
  currentStep: string
  report: ReportResponse | null
  error: string | null
  startDiscovery: (brandUrl: string, location: string, vertical: string) => Promise<void>
  reset: () => void
}

export function useDiscovery(): UseDiscoveryReturn {
  const [status, setStatus]           = useState<DiscoveryStatus>('idle')
  const [progress, setProgress]       = useState(0)
  const [currentStep, setCurrentStep] = useState('')
  const [report, setReport]           = useState<ReportResponse | null>(null)
  const [error, setError]             = useState<string | null>(null)

  const taskIdRef   = useRef<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  useEffect(() => () => stopPolling(), [stopPolling])

  const startDiscovery = useCallback(
    async (brandUrl: string, location: string, vertical: string) => {
      setStatus('loading')
      setProgress(0)
      setCurrentStep(PROGRESS_MESSAGES[0])
      setError(null)
      setReport(null)

      try {
        const { task_id } = await apiStart({
          brand_url: brandUrl,
          location,
          vertical_tag: vertical,
        })
        taskIdRef.current = task_id

        intervalRef.current = setInterval(async () => {
          try {
            const s = await pollStatus(task_id)
            setProgress(s.progress)
            setCurrentStep(getProgressMessage(s.progress))

            if (s.status === 'complete') {
              stopPolling()
              const r = await fetchReport(task_id)
              setReport(r)
              setStatus('complete')
            } else if (s.status === 'error') {
              stopPolling()
              setError('Something went wrong on our end. Please try again.')
              setStatus('error')
            }
          } catch {
            stopPolling()
            setError('Something went wrong on our end. Please try again.')
            setStatus('error')
          }
        }, 2000)
      } catch (err: unknown) {
        const msg =
          err instanceof Error ? err.message : 'Something went wrong. Please try again.'
        setError(msg)
        setStatus('error')
      }
    },
    [stopPolling],
  )

  const reset = useCallback(() => {
    stopPolling()
    setStatus('idle')
    setProgress(0)
    setCurrentStep('')
    setReport(null)
    setError(null)
    taskIdRef.current = null
  }, [stopPolling])

  return { status, progress, currentStep, report, error, startDiscovery, reset }
}
