import { useState } from 'react'
import { cn } from '../../lib/cn'

const PYTHON_SNIPPET = `import hashlib, hmac, time

def verify(secret: bytes, timestamp: str, body: bytes, signature_header: str) -> bool:
    expected = "v1=" + hmac.new(secret, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    if abs(time.time() - int(timestamp)) > 300:
        return False
    return hmac.compare_digest(expected, signature_header)

# secret = this channel's webhook secret
# timestamp = the X-Cronos-Timestamp header
# body = the raw request body bytes
# signature_header = the X-Cronos-Signature header
`

const NODE_SNIPPET = `const crypto = require('crypto')

function verify(secret, timestamp, body, signatureHeader) {
  const expected = 'v1=' + crypto.createHmac('sha256', secret).update(\`\${timestamp}.\`).update(body).digest('hex')
  if (Math.abs(Date.now() / 1000 - Number(timestamp)) > 300) return false
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signatureHeader))
}

// secret = this channel's webhook secret
// timestamp = the X-Cronos-Timestamp header
// body = the raw request body bytes
// signatureHeader = the X-Cronos-Signature header
`

const SNIPPETS = { python: PYTHON_SNIPPET, node: NODE_SNIPPET } as const

export function SignatureSnippet() {
  const [lang, setLang] = useState<keyof typeof SNIPPETS>('python')

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        {(Object.keys(SNIPPETS) as (keyof typeof SNIPPETS)[]).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setLang(key)}
            className={cn(
              'rounded-full border px-3 py-1 font-body text-xs capitalize transition-colors duration-(--duration-fast)',
              lang === key
                ? 'border-accent text-accent'
                : 'border-border text-text-muted hover:text-text',
            )}
          >
            {key}
          </button>
        ))}
      </div>
      <pre className="overflow-x-auto rounded-sm border border-border bg-surface p-4 font-mono text-xs text-text">
        <code>{SNIPPETS[lang]}</code>
      </pre>
    </div>
  )
}
