// Autosave with the house envelope (ADR A.2 PATCH /notes/{id}/autosave): save(body_md, version) resolves
// to {note} or {conflict: true, server_version, server_data}. Debounced 1.5 s after the last edit; one save
// in flight at a time; a conflict hands the whole envelope to onConflict(server) and pauses until the host
// answers it by changing `autosave.version` (keep mine) or `value` (take theirs).

export const AUTOSAVE_DEBOUNCE_MS = 1500
export const AUTOSAVE_RETRY_MS = 5000

/**
 * @param {object} options
 * @param {string} options.body        The saved baseline: the body as the server has it.
 * @param {number} options.version
 * @param {() => {save: Function, onConflict?: Function}} options.getHandlers
 * @param {(state: 'idle'|'dirty'|'saving'|'saved'|'conflict'|'error') => void} options.onState
 */
export function createAutosaver({ body, version, getHandlers, onState, debounceMs = AUTOSAVE_DEBOUNCE_MS, retryMs = AUTOSAVE_RETRY_MS }) {
  let saved = body
  let pending = null
  let current = version
  let timer = null
  let saving = false
  let conflict = false
  let disposed = false
  let state = 'idle'

  const set = (next) => {
    if (next === state || disposed) return
    state = next
    onState(next)
  }
  const arm = (ms) => {
    clearTimeout(timer)
    timer = setTimeout(run, ms)
  }

  async function run() {
    timer = null
    if (disposed || saving || conflict || pending === null || pending === saved) return
    const sending = pending
    const { save, onConflict } = getHandlers()
    saving = true
    set('saving')
    let result
    try {
      result = await save(sending, current)
    } catch {
      saving = false
      set('error')
      arm(retryMs)
      return
    }
    saving = false
    if (result?.conflict) {
      conflict = true
      set('conflict')
      onConflict?.(result)
      return
    }
    saved = sending
    const next = result?.note?.version
    if (typeof next === 'number') current = next
    if (pending === saved) {
      pending = null
      set('saved')
    } else {
      set('dirty')
      arm(debounceMs)
    }
  }

  return {
    /** The body changed. `next` is what would be saved (placeholders stripped). */
    edit(next) {
      pending = next
      if (conflict) return
      if (next === saved && !saving) {
        clearTimeout(timer)
        timer = null
        set(state === 'idle' ? 'idle' : 'saved')
        return
      }
      set('dirty')
      arm(debounceMs)
    },
    /** The host changed `autosave.version`: its answer to a conflict, or a version after its own save. */
    setVersion(next) {
      if (next === current) return
      current = next
      if (conflict) {
        conflict = false
        if (pending !== null && pending !== saved) {
          set('dirty')
          arm(0)
        } else {
          set('idle')
        }
      }
    },
    /** The host replaced the body (take theirs): that is the new baseline and nothing is pending. */
    reset(nextBody, nextVersion) {
      clearTimeout(timer)
      timer = null
      saved = nextBody
      pending = null
      conflict = false
      if (typeof nextVersion === 'number') current = nextVersion
      set('idle')
    },
    /** Save now if anything is waiting (used when the editor unmounts). */
    flush() {
      if (timer !== null || (pending !== null && pending !== saved && !conflict)) {
        clearTimeout(timer)
        void run()
      }
    },
    dispose() {
      disposed = true
      clearTimeout(timer)
    },
    get version() {
      return current
    },
    get state() {
      return state
    },
  }
}
