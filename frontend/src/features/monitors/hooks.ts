import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as monitorsApi from '../../lib/api/monitors'
import { getUsage } from '../../lib/api/usage'
import type { Monitor, MonitorPatchPayload } from '../../lib/api/types'

export const MONITORS_QUERY_KEY = ['monitors'] as const
export const USAGE_QUERY_KEY = ['usage'] as const

function monitorQueryKey(id: string) {
  return ['monitors', id] as const
}

export function useMonitors() {
  return useQuery({
    queryKey: MONITORS_QUERY_KEY,
    queryFn: monitorsApi.listMonitors,
  })
}

export function useMonitor(id: string | undefined) {
  return useQuery({
    queryKey: monitorQueryKey(id ?? ''),
    queryFn: () => monitorsApi.getMonitor(id as string),
    enabled: Boolean(id),
  })
}

export function useUsage() {
  return useQuery({
    queryKey: USAGE_QUERY_KEY,
    queryFn: getUsage,
  })
}

export function useCreateMonitor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: monitorsApi.createMonitor,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MONITORS_QUERY_KEY })
      queryClient.invalidateQueries({ queryKey: USAGE_QUERY_KEY })
    },
  })
}

export function usePatchMonitor(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: MonitorPatchPayload) => monitorsApi.patchMonitor(id, payload),
    onSuccess: (monitor) => {
      queryClient.setQueryData(monitorQueryKey(id), monitor)
      queryClient.invalidateQueries({ queryKey: MONITORS_QUERY_KEY })
    },
  })
}

export function useDeleteMonitor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: monitorsApi.deleteMonitor,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MONITORS_QUERY_KEY })
      queryClient.invalidateQueries({ queryKey: USAGE_QUERY_KEY })
    },
  })
}

export function useCheckNow() {
  return useMutation({
    mutationFn: monitorsApi.checkNowMonitor,
  })
}

function useOptimisticToggle(action: (id: string) => Promise<Monitor>, nextStatus: Monitor['status']) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: action,
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: MONITORS_QUERY_KEY })
      const previous = queryClient.getQueryData<Monitor[]>(MONITORS_QUERY_KEY)
      queryClient.setQueryData<Monitor[]>(MONITORS_QUERY_KEY, (monitors) =>
        monitors?.map((monitor) =>
          monitor.id === id
            ? { ...monitor, status: nextStatus, is_active: nextStatus !== 'paused' }
            : monitor,
        ),
      )
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (context?.previous) queryClient.setQueryData(MONITORS_QUERY_KEY, context.previous)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: MONITORS_QUERY_KEY })
    },
  })
}

export function usePauseMonitor() {
  return useOptimisticToggle(monitorsApi.pauseMonitor, 'paused')
}

export function useResumeMonitor() {
  return useOptimisticToggle(monitorsApi.resumeMonitor, 'new')
}
