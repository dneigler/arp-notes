// C0 helper: a stand-in for an export whose lane has not landed. A lane replaces the stub with its
// implementation and drops the import.

export function notImplemented(name, lane) {
  const stub = () => {
    throw new Error(`${name}: not implemented (${lane})`)
  }
  Object.defineProperty(stub, 'name', { value: name })
  return stub
}
