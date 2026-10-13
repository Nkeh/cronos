const MAILPIT_URL = process.env.MAILPIT_URL ?? 'http://mailpit:8025'

interface MailpitMessage {
  ID: string
  Subject: string
  Snippet: string
}

/** Polls Mailpit's API until a message to `toAddress` with a matching subject arrives. */
export async function waitForEmail(
  toAddress: string,
  subjectContains: string,
  timeoutMs = 15000,
): Promise<MailpitMessage> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const res = await fetch(
      `${MAILPIT_URL}/api/v1/search?query=${encodeURIComponent(`to:${toAddress}`)}`,
    )
    const data = (await res.json()) as { messages: MailpitMessage[] }
    const match = data.messages?.find((m) => m.Subject.includes(subjectContains))
    if (match) return match
    await new Promise((resolve) => setTimeout(resolve, 400))
  }
  throw new Error(`Timed out waiting for an email to ${toAddress} with subject "${subjectContains}"`)
}

export function extractLink(snippet: string): string {
  const match = snippet.match(/https?:\/\/\S+/)
  if (!match) throw new Error(`No link found in email snippet: ${snippet}`)
  return match[0].replace(/[.,]$/, '')
}
