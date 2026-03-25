import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import { electronApp, is, optimizer } from '@electron-toolkit/utils'
import { type ChildProcess, spawn } from 'node:child_process'
import { join } from 'node:path'

let backendProcess: ChildProcess | null = null
const manageBackendInElectron = process.env.BACKEND_MANAGED_EXTERNALLY !== 'true'

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
    titleBarStyle: 'hiddenInset',
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
