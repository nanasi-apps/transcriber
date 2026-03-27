const BACKEND_URL = 'http://127.0.0.1:8765'

// -- Types matching backend JobStatusResponse + TranscriptionResult ----------

export interface WordTimestamp {
  text: string
  start: number
  end: number
}

export interface Utterance {
  speaker_id: string
  start: number
  end: number
  text: string
  words?: WordTimestamp[] | null
}

export interface TranscriptionResult {
  utterances: Utterance[]
  audio_duration: number
  metadata: {
    timings?: Record<string, number>
    [key: string]: unknown
  }
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
  result: TranscriptionResult
  speakerNames: Record<string, string>
}

export interface LinkedMediaFile {
  path: string
  name: string
  exists: boolean
  url: string
}

export interface StoredMinutesMedia {
  recordId: string
  sourceFileName: string
  sourceFilePath: string
}

export interface SaveMinutesInput {
  id?: string
  title: string
  sourceFileName: string
  sourceFilePath: string | null
  recordedAt: string | null
  audioDuration: number
  processingTime: number | null
  result: TranscriptionResult
  speakerNames: Record<string, string>
}

export interface TranscribeJobStatus {
  job_id: string
  status: 'queued' | 'processing' | 'done' | 'error'
  stage: string
  progress: number
  message: string
  processing_time: number | null
  result: TranscriptionResult | null
}

export interface TranscribeUploadResponse {
  job_id: string
}

// -- HTTP helper -------------------------------------------------------------

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BACKEND_URL}${path}`, init)
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || 'Request failed')
  }
  return response.json() as Promise<T>
}

// -- Public API --------------------------------------------------------------

export async function healthCheck(): Promise<boolean> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/health`)
    return response.ok
  } catch {
    return false
  }
}

export async function transcribeUpload(file: File, options?: { align?: boolean }): Promise<string> {
  const formData = new FormData()
  formData.append('file', file)
  const searchParams = new URLSearchParams()
  if (options?.align !== undefined) {
    searchParams.set('align', String(options.align))
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : ''
  const data = await requestJson<TranscribeUploadResponse>(`/api/transcribe/upload${suffix}`, {
    method: 'POST',
    body: formData,
  })
  return data.job_id
}

export async function transcribeStatus(jobId: string): Promise<TranscribeJobStatus> {
  return requestJson<TranscribeJobStatus>(`/api/jobs/${jobId}`)
}

export async function listMinutes(): Promise<MinutesRecord[]> {
  return window.api.listMinutes()
}

export async function getMinutes(id: string): Promise<MinutesRecord | null> {
  return window.api.getMinutes(id)
}

export async function saveMinutes(payload: SaveMinutesInput): Promise<MinutesRecord> {
  return window.api.saveMinutes(payload)
}

export async function storeMinutesMedia(payload: {
  recordId?: string
  sourceFileName: string
  data: Uint8Array | ArrayBuffer
}): Promise<StoredMinutesMedia> {
  return window.api.storeMinutesMedia(payload)
}

export async function deleteMinutes(id: string): Promise<boolean> {
  return window.api.deleteMinutes(id)
}

export async function getLinkedMediaFile(filePath: string): Promise<LinkedMediaFile> {
  return window.api.getLinkedMediaFile(filePath)
}
