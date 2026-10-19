// SHA-256 of a File/Blob through WebCrypto (needs a secure context: https or localhost).

const HEX = Array.from({ length: 256 }, (_, i) => i.toString(16).padStart(2, '0'))

export function bytesToHex(bytes) {
  let out = ''
  for (const b of new Uint8Array(bytes)) out += HEX[b]
  return out
}

/** Lower-case 64-character hex digest of a File or Blob, the form A.4 and the upload ticket expect. */
export async function sha256OfFile(file) {
  const subtle = globalThis.crypto?.subtle
  if (!subtle) throw new Error('sha256OfFile needs WebCrypto, which browsers expose only in secure contexts')
  return bytesToHex(await subtle.digest('SHA-256', await file.arrayBuffer()))
}
