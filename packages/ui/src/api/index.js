// createNotesApi({fetch, fetchRaw, baseUrl}): the A.6 client plus getCapabilities, exportNote, resolveTombstone; ajv validation.
// Owner: C6a ga-mxal.13.

export { createNotesApi, toQuery, parseAttachmentsHeader } from './client.js'
export { NotesApiError, NotesSchemaError } from './errors.js'
export { assertShape, checkShape, schemaNames } from './validate.js'
export { sha256OfFile } from './sha256.js'
export { formatUploadProgress } from './progress.js'
