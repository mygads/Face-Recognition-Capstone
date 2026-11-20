import { createHash } from 'node:crypto'
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const modelUrl =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
const expectedSize = 3_758_596
const expectedSha256 = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'
const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const targetPath = resolve(scriptDirectory, '../public/models/face_landmarker.task')
const temporaryPath = targetPath + '.download'

function isExpectedModel(bytes) {
  return (
    bytes.byteLength === expectedSize &&
    createHash('sha256').update(bytes).digest('hex') === expectedSha256
  )
}

try {
  const existing = await readFile(targetPath)
  if (isExpectedModel(existing)) {
    console.log('Face Landmarker model sudah tersedia secara lokal.')
    process.exit(0)
  }
} catch {
  // Unduh model pada pemakaian pertama; build tetap memakai aset lokal setelahnya.
}

console.log('Mengunduh model Face Landmarker 478 titik dari Google AI Edge…')
const response = await fetch(modelUrl, { signal: AbortSignal.timeout(90_000) })
if (!response.ok) {
  throw new Error('Model Face Landmarker tidak dapat diunduh (HTTP ' + response.status + ').')
}

const model = Buffer.from(await response.arrayBuffer())
if (!isExpectedModel(model)) {
  throw new Error('Ukuran atau checksum model Face Landmarker tidak sesuai.')
}

await mkdir(dirname(targetPath), { recursive: true })
await writeFile(temporaryPath, model)
await rename(temporaryPath, targetPath)
console.log('Model Face Landmarker siap (' + model.byteLength.toLocaleString() + ' byte).')
