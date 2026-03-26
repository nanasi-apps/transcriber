import { app, BrowserWindow, dialog, ipcMain, protocol, shell } from 'electron'
import { electronApp, is, optimizer } from '@electron-toolkit/utils'
import { type ChildProcess, spawn } from 'node:child_process'
import { access, stat } from 'node:fs/promises'
import { createReadStream } from 'node:fs'
import { join } from 'node:path'
import {
  deleteMinutes,
  getMinutes,
  listMinutes,
  saveMinutes,
  type SaveMinutesInput,
} from './minutesStore'

let backendProcess: ChildProcess | null = null
const manageBackendInElectron = process.env.BACKEND_MANAGED_EXTERNALLY !== 'true'

protocol.registerSchemesAsPrivileged([
  {
    scheme: 'media-file',
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true,
    },
  },
])

function createLinkedMediaUrl(filePath: string): string {
  return `media-file://local?path=${encodeURIComponent(filePath)}`
}

function decodeMediaFileUrl(requestUrl: string): string {
  const url = new URL(requestUrl)
  const path = url.searchParams.get('path')
  return path ? decodeURIComponent(path) : ''
}

function parseRangeHeader(rangeHeader: string, size: number): { start: number; end: number } | null {
  const match = /^bytes=(\d*)-(\d*)$/i.exec(rangeHeader.trim())
  if (!match) return null

  const startText = match[1]
  const endText = match[2]

  if (!startText && !endText) return null

  if (!startText) {
    const suffixLength = Number.parseInt(endText, 10)
    if (!Number.isFinite(suffixLength) || suffixLength <= 0) return null
    const start = Math.max(size - suffixLength, 0)
    return { start, end: size - 1 }
  }

  const start = Number.parseInt(startText, 10)
  if (!Number.isFinite(start) || start < 0 || start >= size) return null

  if (!endText) {
    return { start, end: size - 1 }
  }

  const end = Number.parseInt(endText, 10)
  if (!Number.isFinite(end) || end < start) return null

  return { start, end: Math.min(end, size - 1) }
}

function findPythonPath(): string {
  if (is.dev) {
    return join(__dirname, '../../backend/.venv/bin/python')
  }
  return 'python3'
}

function startBackend(): void {
  if (!manageBackendInElectron) {
    return
  }

  const pythonPath = findPythonPath()
  const backendDir = is.dev
    ? join(__dirname, '../../backend')
    : join(process.resourcesPath, 'backend')

  backendProcess = spawn(
    pythonPath,
    ['-m', 'uvicorn', 'transcriber.server:app', '--host', '127.0.0.1', '--port', '8765'],
    {
      cwd: backendDir,
      env: {
        ...process.env,
        PYTHONPATH: join(backendDir, 'src'),
      },
    },
  )

  backendProcess.stdout?.on('data', (data: Buffer) => {
    console.log(`[backend] ${data.toString().trim()}`)
  })

  backendProcess.stderr?.on('data', (data: Buffer) => {
    console.log(`[backend] ${data.toString().trim()}`)
  })

  backendProcess.on('error', (err) => {
    console.error('[backend] Failed to start:', err.message)
  })

  backendProcess.on('exit', (code) => {
    console.log(`[backend] Process exited with code ${code}`)
    backendProcess = null
  })
}

function stopBackend(): void {
  if (!manageBackendInElectron) {
    return
  }

  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
}

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 960,
    height: 680,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
    },
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  if (is.dev && process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(() => {
  electronApp.setAppUserModelId('com.transcriber')

  protocol.handle('media-file', async (request) => {
    const filePath = decodeMediaFileUrl(request.url)
    if (!filePath) {
      return new Response('Missing media file path', { status: 400 })
    }

    let fileInfo
    try {
      fileInfo = await stat(filePath)
    } catch {
      return new Response('Media file not found', { status: 404 })
    }

    const totalSize = fileInfo.size
    const rangeHeader = request.headers.get('range')
    const commonHeaders = {
      'accept-ranges': 'bytes',
      'content-type': 'application/octet-stream',
      'cache-control': 'no-cache',
    }

    if (!rangeHeader) {
      const stream = createReadStream(filePath)
      return new Response(stream as unknown as BodyInit, {
        status: 200,
        headers: {
          ...commonHeaders,
          'content-length': String(totalSize),
        },
      })
    }

    const parsedRange = parseRangeHeader(rangeHeader, totalSize)
    if (!parsedRange) {
      return new Response(null, {
        status: 416,
        headers: {
          ...commonHeaders,
          'content-range': `bytes */${totalSize}`,
        },
      })
    }

    const { start, end } = parsedRange
    const chunkSize = end - start + 1
    const stream = createReadStream(filePath, { start, end })

    return new Response(stream as unknown as BodyInit, {
      status: 206,
      headers: {
        ...commonHeaders,
        'content-length': String(chunkSize),
        'content-range': `bytes ${start}-${end}/${totalSize}`,
      },
    })
  })

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  startBackend()

  ipcMain.handle('dialog:openFile', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
      filters: [
        {
          name: 'Video / Audio',
          extensions: ['mp4', 'wav', 'mp3', 'm4a', 'webm', 'ogg', 'flac'],
        },
      ],
    })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('dialog:openLinkedMediaFile', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
      filters: [
        {
          name: 'Video / Audio',
          extensions: ['mp4', 'wav', 'mp3', 'm4a', 'webm', 'ogg', 'flac', 'mov', 'm4v'],
        },
      ],
    })
    if (result.canceled || !result.filePaths[0]) {
      return null
    }
    const filePath = result.filePaths[0]
    return {
      filePath,
      filename: filePath.split(/[/\\]/).pop() ?? filePath,
    }
  })

  ipcMain.handle('minutes:list', async () => {
    return listMinutes()
  })

  ipcMain.handle('minutes:get', async (_, id: string) => {
    return getMinutes(id)
  })

  ipcMain.handle('minutes:save', async (_, payload: SaveMinutesInput) => {
    return saveMinutes(payload)
  })

  ipcMain.handle('minutes:delete', async (_, id: string) => {
    return deleteMinutes(id)
  })

  ipcMain.handle('minutes:getLinkedMediaFile', async (_, filePath: string) => {
    let exists = false
    try {
      await access(filePath)
      exists = true
    } catch {
      exists = false
    }

    return {
      path: filePath,
      name: filePath.split(/[/\\]/).pop() ?? filePath,
      exists,
      url: exists ? createLinkedMediaUrl(filePath) : '',
    }
  })

  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  stopBackend()
})
