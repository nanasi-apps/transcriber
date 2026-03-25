import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'

const BACKEND_URL = 'http://127.0.0.1:8765'

export interface TranscribeResult {
  jobId: string
}

export interface TranscribeOptions {
  keywords?: string
}

export interface UploadResult {
  filePath: string
  filename: string
}

export interface TranscribeJobStatus {
  status: 'queued' | 'loading' | 'processing' | 'done' | 'error'
  progress: number
  message: string
  text: string | null
}

const api = {
  selectFile: (): Promise<string | null> => ipcRenderer.invoke('dialog:openFile'),

  transcribe: async (
    filePath: string,
    options: TranscribeOptions = {},
  ): Promise<TranscribeResult> => {
    const response = await fetch(`${BACKEND_URL}/api/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath, keywords: options.keywords ?? null }),
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Transcription failed')
    }
    const data = await response.json()
    return { jobId: data.job_id }
  },

  transcribeStatus: async (jobId: string): Promise<TranscribeJobStatus> => {
    const response = await fetch(`${BACKEND_URL}/api/transcribe/${jobId}`)
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to fetch progress')
    }
    return response.json()
  },

  uploadFile: async (file: File): Promise<UploadResult> => {
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`${BACKEND_URL}/api/upload`, {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to upload file')
    }

    return response.json()
  },

  selectWebFile: (): Promise<File | null> => {
    return new Promise((resolve) => {
      const input = document.createElement('input')
      input.type = 'file'
      input.accept = '.mp4,.wav,.mp3,.m4a,.webm,.ogg,.flac'
      input.onchange = () => resolve(input.files?.[0] ?? null)
      input.click()
    })
  },

  healthCheck: async (): Promise<boolean> => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/health`)
      return response.ok
    } catch {
      return false
    }
  },
}

export type ApiType = typeof api

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', electronAPI)
    contextBridge.exposeInMainWorld('api', api)
  } catch (error) {
    console.error(error)
  }
} else {
  // @ts-expect-error fallback for non-isolated context
  window.electron = electronAPI
  // @ts-expect-error fallback for non-isolated context
  window.api = api
}
