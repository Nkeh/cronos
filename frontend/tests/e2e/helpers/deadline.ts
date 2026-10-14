/**
 * Races `promise` against an explicit wall-clock deadline, throwing a message that names what
 * was being waited for. Used anywhere a hang would otherwise be silent (globalSetup, dev-fixture
 * HTTP calls, login) — two prior sessions lost an hour and 13 hours respectively to a Playwright
 * invocation that produced no output and never exited; every potentially-blocking await in the
 * e2e harness must have an explicit, named ceiling so a stall fails loudly instead.
 */
export async function withDeadline<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout>
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`Timed out after ${ms}ms waiting for: ${label}`)), ms)
  })
  try {
    return await Promise.race([promise, timeout])
  } finally {
    clearTimeout(timer)
  }
}
