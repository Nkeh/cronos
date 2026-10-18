import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as incidentsApi from '../../lib/api/incidents'

export const OPEN_INCIDENT_COUNT_QUERY_KEY = ['incidents', 'open-count'] as const

function incidentsListQueryKey(state: 'open' | 'resolved') {
  return ['incidents', 'list', state] as const
}

function incidentQueryKey(id: string) {
  return ['incidents', id] as const
}

export function useIncidents(state: 'open' | 'resolved') {
  return useInfiniteQuery({
    queryKey: incidentsListQueryKey(state),
    queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
      incidentsApi.listIncidents({ state, cursor: pageParam, limit: 25 }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })
}

export function useIncident(id: string | undefined) {
  return useQuery({
    queryKey: incidentQueryKey(id ?? ''),
    queryFn: () => incidentsApi.getIncident(id as string),
    enabled: Boolean(id),
  })
}

/** Backs the navbar's pulsing incident badge -- 10s poll, cheap enough for a count query and
 * frequent enough that a freshly opened incident shows up without a manual refresh. */
export function useOpenIncidentCount() {
  return useQuery({
    queryKey: OPEN_INCIDENT_COUNT_QUERY_KEY,
    queryFn: incidentsApi.getOpenIncidentCount,
    refetchInterval: 10_000,
  })
}

export function useAckIncident(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => incidentsApi.ackIncident(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: incidentQueryKey(id) })
      queryClient.invalidateQueries({ queryKey: ['incidents', 'list'] })
      queryClient.invalidateQueries({ queryKey: OPEN_INCIDENT_COUNT_QUERY_KEY })
    },
  })
}
