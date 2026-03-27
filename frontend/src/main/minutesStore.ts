import { app } from 'electron'
import { randomUUID } from 'node:crypto'
import { mkdir, readFile, readdir, unlink, writeFile } from 'node:fs/promises'
import { extname, join } from 'node:path'

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
  sourceFilePath: string | null
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
  sourceFilePath: string | null
  recordedAt: string | null
  audioDuration: number
  processingTime: number | null
  result: StoredTranscriptionResult
  speakerNames: Record<string, string>
}

export interface StoreMinutesMediaInput {
  recordId?: string
  sourceFileName: string
  data: Uint8Array | ArrayBuffer
}

export interface StoredMinutesMedia {
  recordId: string
  sourceFileName: string
  sourceFilePath: string
}

interface MinutesStoreFile {
  version: number
  records: MinutesRecord[]
}

const STORE_VERSION = 2
const STORE_FILE_NAME = 'minutes-store.json'
const MEDIA_DIR_NAME = 'minutes-media'

function normalizeRecord(record: Partial<MinutesRecord>): MinutesRecord {
  return {
    id: typeof record.id === 'string' ? record.id : randomUUID(),
    title: typeof record.title === 'string' ? record.title : '議事録ビュー',
    sourceFileName: typeof record.sourceFileName === 'string' ? record.sourceFileName : 'unknown',
    sourceFilePath: typeof record.sourceFilePath === 'string' ? record.sourceFilePath : null,
    savedAt: typeof record.savedAt === 'string' ? record.savedAt : new Date().toISOString(),
    recordedAt: typeof record.recordedAt === 'string' ? record.recordedAt : null,
    audioDuration: typeof record.audioDuration === 'number' ? record.audioDuration : 0,
    processingTime: typeof record.processingTime === 'number' ? record.processingTime : null,
    result: record.result as StoredTranscriptionResult,
    speakerNames: record.speakerNames && typeof record.speakerNames === 'object' ? record.speakerNames : {},
  }
}

function getStorePath(): string {
  return join(app.getPath('userData'), STORE_FILE_NAME)
}

function getMediaDirPath(): string {
  return join(app.getPath('userData'), MEDIA_DIR_NAME)
}

function normalizeMediaPayload(data: Uint8Array | ArrayBuffer): Uint8Array {
  return data instanceof Uint8Array ? data : new Uint8Array(data)
}

function getManagedMediaPrefix(recordId: string): string {
  return `${recordId}.`
}

async function removeManagedMediaFiles(recordId: string): Promise<void> {
  const mediaDirPath = getMediaDirPath()
  try {
    const entries = await readdir(mediaDirPath)
    const managedPrefix = getManagedMediaPrefix(recordId)
    await Promise.all(
      entries
        .filter((entry) => entry.startsWith(managedPrefix))
        .map((entry) => unlink(join(mediaDirPath, entry)).catch(() => undefined)),
    )
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
      throw error
    }
  }
}

function isManagedMediaPath(filePath: string): boolean {
  return filePath.startsWith(`${getMediaDirPath()}/`) || filePath.startsWith(`${getMediaDirPath()}\\`)
}

async function readStore(): Promise<MinutesStoreFile> {
  try {
    const raw = await readFile(getStorePath(), 'utf-8')
    const parsed = JSON.parse(raw) as Partial<MinutesStoreFile>
    return {
      version: STORE_VERSION,
      records: Array.isArray(parsed.records) ? parsed.records.map((record) => normalizeRecord(record)) : [],
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
    sourceFilePath: input.sourceFilePath,
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

export async function storeMinutesMedia(input: StoreMinutesMediaInput): Promise<StoredMinutesMedia> {
  const recordId = input.recordId ?? randomUUID()
  const sourceFileName = input.sourceFileName || 'unknown'
  const extension = extname(sourceFileName) || '.bin'
  const mediaDirPath = getMediaDirPath()
  const targetPath = join(mediaDirPath, `${recordId}${extension.toLowerCase()}`)

  await mkdir(mediaDirPath, { recursive: true })
  await removeManagedMediaFiles(recordId)
  await writeFile(targetPath, normalizeMediaPayload(input.data))

  return {
    recordId,
    sourceFileName,
    sourceFilePath: targetPath,
  }
}

export async function deleteMinutes(id: string): Promise<boolean> {
  const store = await readStore()
  const deletedRecord = store.records.find((record) => record.id === id) ?? null
  const nextRecords = store.records.filter((record) => record.id !== id)
  if (nextRecords.length === store.records.length) {
    return false
  }

  await writeStore({ version: STORE_VERSION, records: sortRecords(nextRecords) })
  if (deletedRecord?.sourceFilePath && isManagedMediaPath(deletedRecord.sourceFilePath)) {
    await removeManagedMediaFiles(id)
  }
  return true
}
