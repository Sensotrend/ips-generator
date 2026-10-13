import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './client'
import type { Draft, JobEvent, ReviewAction, ReviewerRole } from './types'

export const keys = {
  jobs: ['jobs'] as const,
  job: (id: string) => ['job', id] as const,
  draft: (id: string) => ['draft', id] as const,
  source: (id: string) => ['source', id] as const,
}

export const useJobs = () => useQuery({ queryKey: keys.jobs, queryFn: api.listJobs })

export const useJob = (id: string) =>
  useQuery({ queryKey: keys.job(id), queryFn: () => api.getJob(id) })

export const useDraft = (id: string, enabled: boolean) =>
  useQuery({ queryKey: keys.draft(id), queryFn: () => api.getDraft(id), enabled })

export const useSource = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: keys.source(id),
    queryFn: () => api.getSource(id),
    enabled,
    staleTime: Infinity,
  })

export function useUpdateDraft(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ version, actions }: { version: number; actions: ReviewAction[] }) =>
      api.updateDraft(id, version, actions),
    onSuccess: (draft: Draft) => client.setQueryData(keys.draft(id), draft),
  })
}

export function useApprove(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ version, role }: { version: number; role: ReviewerRole }) =>
      api.approve(id, version, role),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.job(id) })
      void client.invalidateQueries({ queryKey: keys.draft(id) })
    },
  })
}

const TERMINAL = new Set(['review_ready', 'failed', 'approved'])

/** Job progress over SSE. Closes on a terminal job event and refreshes the job. */
export function useJobEvents(id: string, enabled: boolean): JobEvent[] {
  const client = useQueryClient()
  const [events, setEvents] = useState<JobEvent[]>([])
  useEffect(() => {
    if (!enabled) return
    const source = new EventSource(api.eventsUrl(id))
    source.onmessage = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as JobEvent
      setEvents((previous) =>
        previous.some((e) => e.seq === event.seq) ? previous : [...previous, event],
      )
      if (event.step === 'job' && TERMINAL.has(event.status)) {
        source.close()
        void client.invalidateQueries({ queryKey: keys.job(id) })
      }
    }
    return () => source.close()
  }, [id, enabled, client])
  return events
}
