import { app } from 'electron'
import { randomUUID } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

export interface StoredWordTimestamp {
  text: string
  start: number
  end: number
}

export interface StoredUtterance {
  speaker_id: string
  start: number
  end: number
  text: string
  words?: StoredWordTimestamp[] | null
}

export interface StoredTranscriptionResult {
  utterances: StoredUtterance[]
  audio_duration: number
  metadata: Record<string, unknown>
}

export interface MinutesRecord {
  id: string
  title: string
  sourceFileName: string
  savedAt: string
  recordedAt: string | null
  audioDuration: number
  processingTime: number | null
  result: StoredTranscriptionResult
  speakerNames: Record<string, string>
}

export interface SaveMinutesInput {
  id?: string
  title: string
  sourceFileName: string
  recordedAt: string | null
  audioDuration: number
  processingTime: number | null
  result: StoredTranscriptionResult
  speakerNames: Record<string, string>
}

interface MinutesStoreFile {
  version: number
  records: MinutesRecord[]
}

const STORE_VERSION = 1
const STORE_FILE_NAME = 'minutes-store.json'

function getStorePath(): string {
  return join(app.getPath('userData'), STORE_FILE_NAME)
}

async function readStore(): Promise<MinutesStoreFile> {
  try {
    const raw = await readFile(getStorePath(), 'utf-8')
    const parsed = JSON.parse(raw) as Partial<MinutesStoreFile>
    return {
      version: STORE_VERSION,
      records: Array.isArray(parsed.records) ? parsed.records : [],
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return { version: STORE_VERSION, records: [] }
    }
    throw error
  }
}

async function writeStore(store: MinutesStoreFile): Promise<void> {
  await mkdir(app.getPath('userData'), { recursive: true })
  await writeFile(getStorePath(), JSON.stringify(store, null, 2), 'utf-8')
}

function sortRecords(records: MinutesRecord[]): MinutesRecord[] {
  return [...records].sort((left, right) => {
    return new Date(right.savedAt).getTime() - new Date(left.savedAt).getTime()
  })
}

export async function listMinutes(): Promise<MinutesRecord[]> {
  const store = await readStore()
  return sortRecords(store.records)
}

export async function getMinutes(id: string): Promise<MinutesRecord | null> {
  const store = await readStore()
  return store.records.find((record) => record.id === id) ?? null
}

export async function saveMinutes(input: SaveMinutesInput): Promise<MinutesRecord> {
  const store = await readStore()
  const savedAt = new Date().toISOString()
  const record: MinutesRecord = {
    id: input.id ?? randomUUID(),
    title: input.title,
    sourceFileName: input.sourceFileName,
    savedAt,
    recordedAt: input.recordedAt,
    audioDuration: input.audioDuration,
    processingTime: input.processingTime,
    result: input.result,
    speakerNames: input.speakerNames,
  }

  const existingIndex = store.records.findIndex((item) => item.id === record.id)
  if (existingIndex >= 0) {
    store.records[existingIndex] = record
  } else {
    store.records.push(record)
  }

  await writeStore({ version: STORE_VERSION, records: sortRecords(store.records) })
  return record
}

export async function deleteMinutes(id: string): Promise<boolean> {
  const store = await readStore()
  const nextRecords = store.records.filter((record) => record.id !== id)
  if (nextRecords.length === store.records.length) {
    return false
  }

  await writeStore({ version: STORE_VERSION, records: sortRecords(nextRecords) })
  return true
}
