export interface ApiErrorBody {
  code: string
  message: string
  field?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly field?: string
  readonly retryAfter?: number

  constructor(status: number, body: ApiErrorBody, retryAfter?: number) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.field = body.field
    this.retryAfter = retryAfter
  }
}
