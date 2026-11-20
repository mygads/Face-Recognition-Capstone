import { writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { FaceLandmarker } from '@mediapipe/tasks-vision'

const directory = dirname(fileURLToPath(import.meta.url))
const outputPath = resolve(directory, '../src/utils/faceMeshTopology.ts')

const topology = {
  FACE_MESH_TESSELLATION: FaceLandmarker.FACE_LANDMARKS_TESSELATION,
  FACE_MESH_CONTOURS: FaceLandmarker.FACE_LANDMARKS_CONTOURS,
  FACE_MESH_FACE_OVAL: FaceLandmarker.FACE_LANDMARKS_FACE_OVAL,
  FACE_MESH_LIPS: FaceLandmarker.FACE_LANDMARKS_LIPS,
  FACE_MESH_LEFT_EYE: FaceLandmarker.FACE_LANDMARKS_LEFT_EYE,
  FACE_MESH_RIGHT_EYE: FaceLandmarker.FACE_LANDMARKS_RIGHT_EYE,
  FACE_MESH_LEFT_EYEBROW: FaceLandmarker.FACE_LANDMARKS_LEFT_EYEBROW,
  FACE_MESH_RIGHT_EYEBROW: FaceLandmarker.FACE_LANDMARKS_RIGHT_EYEBROW,
}

const declarations = Object.entries(topology)
  .map(([name, connections]) => {
    const pairs = connections.flatMap(({ start, end }) => [start, end])
    return (
      '// prettier-ignore\nexport const ' + name + ' = new Uint16Array([' + pairs.join(',') + '])'
    )
  })
  .join('\n\n')

await writeFile(
  outputPath,
  [
    '/**',
    ' * Landmark connections from @mediapipe/tasks-vision 1.2.3.',
    ' * Copyright 2022 The MediaPipe Authors; licensed under Apache-2.0.',
    ' * Keep this topology version aligned with the pinned runtime and task model.',
    ' */',
    declarations,
    '',
  ].join('\n'),
)
console.log('Generated Face Landmarker topology at ' + outputPath)
