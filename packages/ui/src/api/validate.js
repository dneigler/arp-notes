// ajv over the schemas vendored from packages/core (scripts/vendor-schemas.mjs).
import Ajv2020 from 'ajv/dist/2020.js'
import { NotesSchemaError } from './errors.js'
import { schemas } from './schemas/index.js'

// strict:false because the generated documents carry annotation keywords (title, description).
// allErrors:false keeps validation of large list responses cheap.
const ajv = new Ajv2020({ strict: false, allErrors: false })
const compiled = new Map()

function validatorFor(name) {
  let fn = compiled.get(name)
  if (!fn) {
    const schema = schemas[name]
    if (!schema) throw new Error(`No vendored schema named ${name}`)
    fn = ajv.compile(schema)
    compiled.set(name, fn)
  }
  return fn
}

/** Returns `value` when it matches the named core model, else throws NotesSchemaError. */
export function assertShape(name, value) {
  const fn = validatorFor(name)
  if (!fn(value)) throw new NotesSchemaError(name, fn.errors, value)
  return value
}

/** Non-throwing variant: `{ ok, errors }`. */
export function checkShape(name, value) {
  const fn = validatorFor(name)
  const ok = fn(value)
  return { ok, errors: ok ? [] : fn.errors }
}

export const schemaNames = () => Object.keys(schemas)
