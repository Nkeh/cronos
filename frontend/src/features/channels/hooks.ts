import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as channelsApi from '../../lib/api/channels'
import type { ChannelCreatePayload, ChannelPatchPayload } from '../../lib/api/types'

export const CHANNELS_QUERY_KEY = ['channels'] as const

function deliveriesQueryKey(channelId: string) {
  return ['channels', channelId, 'deliveries'] as const
}

function monitorChannelsQueryKey(monitorId: string) {
  return ['monitors', monitorId, 'channels'] as const
}

export function useChannels() {
  return useQuery({
    queryKey: CHANNELS_QUERY_KEY,
    queryFn: channelsApi.listChannels,
  })
}

export function useCreateChannel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ChannelCreatePayload) => channelsApi.createChannel(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_QUERY_KEY }),
  })
}

export function usePatchChannel(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ChannelPatchPayload) => channelsApi.patchChannel(id, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_QUERY_KEY }),
  })
}

export function useDeleteChannel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: channelsApi.deleteChannel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_QUERY_KEY }),
  })
}

export function useVerifyChannel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: channelsApi.verifyChannel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_QUERY_KEY }),
  })
}

export function useVerifyChannelEmail() {
  return useMutation({
    mutationFn: channelsApi.verifyChannelEmail,
  })
}

export function useTestChannel() {
  return useMutation({
    mutationFn: channelsApi.testChannel,
  })
}

export function useRotateSecret(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => channelsApi.rotateChannelSecret(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_QUERY_KEY }),
  })
}

export function useRevealSecret() {
  return useMutation({
    mutationFn: channelsApi.revealChannelSecret,
  })
}

export function useChannelDeliveries(channelId: string | undefined) {
  return useInfiniteQuery({
    queryKey: deliveriesQueryKey(channelId ?? ''),
    queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
      channelsApi.listChannelDeliveries(channelId as string, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: Boolean(channelId),
  })
}

export function useMonitorChannels(monitorId: string | undefined) {
  return useQuery({
    queryKey: monitorChannelsQueryKey(monitorId ?? ''),
    queryFn: () => channelsApi.getMonitorChannels(monitorId as string),
    enabled: Boolean(monitorId),
  })
}

export function useSetMonitorChannels(monitorId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (channelIds: string[]) => channelsApi.setMonitorChannels(monitorId, channelIds),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: monitorChannelsQueryKey(monitorId) }),
  })
}
