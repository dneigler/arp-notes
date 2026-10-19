// Errors thrown by the notes API client.

/** A non-2xx answer. `code` is the body's `error` field when the server sent one (e.g. 'read_only_import'). */
export class NotesApiError extends Error {
  constructor(message, { status, body = null, code = null } = {}) {
    super(message)
    this.name = 'NotesApiError'
    this.status = status
    this.body = body
    this.code = code
  }
}

/** A 2xx answer that does not match the vendored core schema (drift, a proxy, or a bug). */
export class NotesSchemaError extends Error {
  constructor(schemaName, errors, value) {
    const first = errors?.[0]
    const where = first ? ` at ${first.instancePath || '/'} ${first.message}` : ''
    super(`Response does not match ${schemaName}${where}`)
    this.name = 'NotesSchemaError'
    this.schemaName = schemaName
    this.errors = errors
    this.value = value
  }
}
