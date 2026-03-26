<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  toRaw,
  type ComponentPublicInstance,
  watch,
} from 'vue'
import {
  deleteMinutes,
  healthCheck,
  listMinutes,
  saveMinutes,
  transcribeStatus,
  transcribeUpload,
  type MinutesRecord,
  type TranscriptionResult,
  type Utterance,
} from '../lib/transcribeApi'

const selectedFile = ref<File | null>(null)
const result = ref<TranscriptionResult | null>(null)
const isTranscribing = ref(false)
const errorMessage = ref('')
const backendReady = ref(false)
const isDragOver = ref(false)
const autoStartRequested = ref(false)
const progress = ref(0)
const progressStage = ref('')
const progressMessage = ref('Starting...')
const processingTime = ref<number | null>(null)
const mediaUrl = ref('')
const currentTime = ref(0)
const selectedAt = ref<Date | null>(null)
const utteranceRefs = ref<HTMLElement[]>([])
const mediaElement = ref<HTMLMediaElement | null>(null)
const speakerNames = ref<Record<string, string>>({})
const savedMinutes = ref<MinutesRecord[]>([])
const currentRecordId = ref<string | null>(null)
const activeTitle = ref('')
const sourceFileName = ref('')
const saveFeedback = ref('')
const isSaving = ref(false)
const isLoadingSaved = ref(false)
const isHydratingRecord = ref(false)
let speakerNameSaveTimer: ReturnType<typeof window.setTimeout> | null = null

const dateTimeFormatter = new Intl.DateTimeFormat('ja-JP', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

onMounted(() => {
  void initializeView()
})

const utterances = computed<Utterance[]>(() => result.value?.utterances ?? [])
const hasResult = computed(() => utterances.value.length > 0)
const hasMedia = computed(() => mediaUrl.value.length > 0)
const activeRecord = computed(() => {
  return savedMinutes.value.find((record) => record.id === currentRecordId.value) ?? null
})
const visibleSourceFileName = computed(() => {
  if (selectedFile.value) return selectedFile.value.name
  return sourceFileName.value
})
const isVideoFile = computed(() => {
  if (!selectedFile.value) return false
  if (selectedFile.value.type.startsWith('video/')) return true
  return /\.(mp4|webm|mov|m4v)$/i.test(selectedFile.value.name)
})
const meetingTitle = computed(() => {
  if (activeTitle.value) return activeTitle.value
  if (!selectedFile.value) return '議事録ビュー'
  const baseName = selectedFile.value.name.replace(/\.[^.]+$/, '')
  return baseName || selectedFile.value.name
})
const recordedAtLabel = computed(() => {
  if (!selectedAt.value) return 'ローカルファイルを選択してください'
  return dateTimeFormatter.format(selectedAt.value)
})
const saveStatusLabel = computed(() => {
  if (isSaving.value) return '保存中...'
  if (saveFeedback.value) return saveFeedback.value
  if (activeRecord.value?.savedAt) {
    return `${dateTimeFormatter.format(new Date(activeRecord.value.savedAt))} に保存済み`
  }
  return '未保存'
})
const activeUtteranceIndex = computed(() => {
  const time = currentTime.value
  return utterances.value.findIndex((utt, index) => {
    const next = utterances.value[index + 1]
    const endBoundary = next ? Math.max(utt.end, next.start - 0.05) : utt.end + 0.2
    return time >= Math.max(0, utt.start - 0.05) && time <= endBoundary
  })
})
const stageTimings = computed<Record<string, number>>(() => {
  const timings = result.value?.metadata?.timings
  return timings && typeof timings === 'object' ? timings : {}
})
const statusBadge = computed(() => {
  if (errorMessage.value) {
    return { label: 'エラー', tone: 'danger', detail: errorMessage.value }
  }
  if (!backendReady.value) {
    return { label: 'バックエンド起動中', tone: 'warning', detail: '処理サーバーを確認しています' }
  }
  if (isTranscribing.value) {
    return { label: '処理中', tone: 'info', detail: progressMessage.value }
  }
  if (hasResult.value) {
    return { label: '作成完了', tone: 'success', detail: '議事録を確認できます' }
  }
  if (selectedFile.value) {
    return { label: '準備完了', tone: 'neutral', detail: '文字起こしを開始できます' }
  }
  return { label: '未開始', tone: 'neutral', detail: 'ファイルをアップロードしてください' }
})

onBeforeUnmount(() => {
  clearMediaUrl()
  clearSpeakerNameSaveTimer()
})

const SPEAKER_COLORS = ['#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed', '#db2777', '#0891b2', '#65a30d']

const speakerColorMap = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  const speakers = [...new Set(utterances.value.map((u) => u.speaker_id))]
  speakers.forEach((id, i) => {
    map[id] = SPEAKER_COLORS[i % SPEAKER_COLORS.length]
  })
  return map
})

const speakerSummaries = computed(() => {
  const stats = new Map<string, { id: string; count: number; duration: number; color: string }>()
  utterances.value.forEach((utterance) => {
    const existing = stats.get(utterance.speaker_id) ?? {
      id: utterance.speaker_id,
      count: 0,
      duration: 0,
      color: speakerColorMap.value[utterance.speaker_id] ?? SPEAKER_COLORS[0],
    }
    existing.count += 1
    existing.duration += Math.max(utterance.end - utterance.start, 0)
    stats.set(utterance.speaker_id, existing)
  })
  return [...stats.values()].sort((left, right) => right.duration - left.duration)
})

function displaySpeakerName(speakerId: string): string {
  const customName = speakerNames.value[speakerId]?.trim()
  return customName || speakerId
}

function formatTime(seconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const secs = totalSeconds % 60
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`
}

function formatProcessingTime(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}m ${s.toFixed(1)}s`
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unitIndex]}`
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    queued: 'Queued',
    audio_prep: 'Preparing audio...',
    asr: 'Running speech recognition...',
    diarization: 'Identifying speakers...',
    alignment: 'Aligning words...',
    merge: 'Merging results...',
    done: 'Complete',
  }
  return labels[stage] ?? stage
}

function clearSpeakerNameSaveTimer(): void {
  if (speakerNameSaveTimer !== null) {
    window.clearTimeout(speakerNameSaveTimer)
    speakerNameSaveTimer = null
  }
}

function toPlainData<T>(value: T): T {
  return structuredClone(toRaw(value))
}

async function initializeView(): Promise<void> {
  await loadSavedMinutes()
  if (!selectedFile.value && !hasResult.value && savedMinutes.value[0]) {
    await loadSavedRecord(savedMinutes.value[0])
  }
  void waitForBackendReady()
}

async function waitForBackendReady(): Promise<void> {
  for (let i = 0; i < 30; i++) {
    if (await healthCheck()) {
      backendReady.value = true
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  errorMessage.value = 'Backend server failed to start.'
}

async function loadSavedMinutes(): Promise<void> {
  try {
    savedMinutes.value = await listMinutes()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存済み議事録の読み込みに失敗しました'
  }
}

function setFile(file: File | null): void {
  clearMediaUrl()
  selectedFile.value = file
  autoStartRequested.value = !!file
  result.value = null
  speakerNames.value = {}
  errorMessage.value = ''
  currentTime.value = 0
  progress.value = 0
  progressStage.value = ''
  progressMessage.value = 'Starting...'
  processingTime.value = null
  selectedAt.value = file ? new Date() : null
  currentRecordId.value = null
  activeTitle.value = file ? deriveTitle(file.name) : ''
  sourceFileName.value = file?.name ?? ''
  saveFeedback.value = ''
  if (file) {
    mediaUrl.value = URL.createObjectURL(file)
  }
}

function clearMediaUrl(): void {
  if (mediaUrl.value) {
    URL.revokeObjectURL(mediaUrl.value)
    mediaUrl.value = ''
  }
}

function deriveTitle(fileName: string): string {
  const baseName = fileName.replace(/\.[^.]+$/, '')
  return baseName || fileName || '議事録ビュー'
}

function onFileInput(event: Event): void {
  const input = event.target as HTMLInputElement
  setFile(input.files?.[0] ?? null)
}

function handleDrop(event: DragEvent): void {
  isDragOver.value = false
  setFile(event.dataTransfer?.files?.[0] ?? null)
}

function handleDragOver(event: DragEvent): void {
  event.preventDefault()
  isDragOver.value = true
}

function handleDragLeave(): void {
  isDragOver.value = false
}

async function startTranscription(): Promise<void> {
  if (!selectedFile.value) return

  autoStartRequested.value = false
  isTranscribing.value = true
  errorMessage.value = ''
  result.value = null
  progress.value = 0
  progressStage.value = ''
  progressMessage.value = 'Uploading file...'
  processingTime.value = null
  saveFeedback.value = ''

  try {
    const jobId = await transcribeUpload(selectedFile.value, { align: true })

    while (true) {
      const status = await transcribeStatus(jobId)
      progress.value = status.progress
      progressStage.value = status.stage
      progressMessage.value = status.message || stageLabel(status.stage)
      processingTime.value = status.processing_time

      if (status.status === 'done' && status.result) {
        result.value = status.result
        sourceFileName.value = selectedFile.value.name
        activeTitle.value = deriveTitle(selectedFile.value.name)
        await persistCurrentMinutes(true)
        break
      }

      if (status.status === 'error') {
        throw new Error(status.message)
      }

      await new Promise((resolve) => setTimeout(resolve, 1000))
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Transcription failed'
  } finally {
    isTranscribing.value = false
  }
}

function resultAsText(): string {
  if (!result.value) return ''
  return result.value.utterances
    .map((u) => `[${displaySpeakerName(u.speaker_id)}] (${formatTime(u.start)} - ${formatTime(u.end)})\n${u.text}`)
    .join('\n\n')
}

function updateSpeakerName(speakerId: string, value: string): void {
  speakerNames.value = {
    ...speakerNames.value,
    [speakerId]: value,
  }
}

function onSpeakerNameInput(speakerId: string, event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  updateSpeakerName(speakerId, target.value)
}

async function copyToClipboard(): Promise<void> {
  const text = resultAsText()
  if (text) {
    await navigator.clipboard.writeText(text)
  }
}

async function persistCurrentMinutes(isAutoSaved = false): Promise<void> {
  if (!result.value) return

  isSaving.value = true
  try {
    const savedRecord = await saveMinutes({
      id: currentRecordId.value ?? undefined,
      title: meetingTitle.value,
      sourceFileName: visibleSourceFileName.value || 'unknown',
      recordedAt: selectedAt.value ? selectedAt.value.toISOString() : null,
      audioDuration: result.value.audio_duration,
      processingTime: processingTime.value,
      result: toPlainData(result.value),
      speakerNames: toPlainData(speakerNames.value),
    })
    currentRecordId.value = savedRecord.id
    activeTitle.value = savedRecord.title
    sourceFileName.value = savedRecord.sourceFileName
    upsertSavedRecord(savedRecord)
    saveFeedback.value = isAutoSaved ? '自動保存しました' : '保存しました'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '議事録の保存に失敗しました'
  } finally {
    isSaving.value = false
  }
}

function upsertSavedRecord(record: MinutesRecord): void {
  const next = savedMinutes.value.filter((item) => item.id !== record.id)
  next.unshift(record)
  savedMinutes.value = next.sort((left, right) => {
    return new Date(right.savedAt).getTime() - new Date(left.savedAt).getTime()
  })
}

async function loadSavedRecord(record: MinutesRecord): Promise<void> {
  isHydratingRecord.value = true
  isLoadingSaved.value = true
  clearSpeakerNameSaveTimer()
  clearMediaUrl()
  selectedFile.value = null
  autoStartRequested.value = false
  result.value = record.result
  speakerNames.value = { ...record.speakerNames }
  processingTime.value = record.processingTime
  selectedAt.value = record.recordedAt ? new Date(record.recordedAt) : null
  currentRecordId.value = record.id
  activeTitle.value = record.title
  sourceFileName.value = record.sourceFileName
  currentTime.value = 0
  progress.value = 0
  progressStage.value = 'done'
  progressMessage.value = '保存済み議事録を表示中'
  errorMessage.value = ''
  saveFeedback.value = `${dateTimeFormatter.format(new Date(record.savedAt))} に保存済み`
  await nextTick()
  isLoadingSaved.value = false
  isHydratingRecord.value = false
}

async function removeSavedRecord(record: MinutesRecord): Promise<void> {
  try {
    const deleted = await deleteMinutes(record.id)
    if (!deleted) return
    savedMinutes.value = savedMinutes.value.filter((item) => item.id !== record.id)
    saveFeedback.value = '保存データを削除しました'

    if (currentRecordId.value !== record.id) return

    currentRecordId.value = null
    if (!selectedFile.value) {
      const fallback = savedMinutes.value[0]
      if (fallback) {
        await loadSavedRecord(fallback)
      } else {
        result.value = null
        speakerNames.value = {}
        activeTitle.value = ''
        sourceFileName.value = ''
        selectedAt.value = null
        processingTime.value = null
      }
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存データの削除に失敗しました'
  }
}

function onMediaTimeUpdate(event: Event): void {
  const target = event.target as HTMLMediaElement
  currentTime.value = target.currentTime || 0
}

function seekTo(seconds: number): void {
  const media = mediaElement.value
  if (!media) return
  media.currentTime = Math.max(0, seconds)
  currentTime.value = media.currentTime
  void media.play().catch(() => undefined)
}

function setUtteranceRef(element: Element | ComponentPublicInstance | null, index: number): void {
  if (!element) return
  const resolvedElement = '$el' in element ? element.$el : element
  if (!(resolvedElement instanceof HTMLElement)) return
  utteranceRefs.value[index] = resolvedElement
}

watch(utterances, () => {
  utteranceRefs.value = []
})

watch(speakerSummaries, (summaries) => {
  const nextNames: Record<string, string> = {}
  summaries.forEach((speaker) => {
    nextNames[speaker.id] = speakerNames.value[speaker.id] ?? ''
  })
  speakerNames.value = nextNames
})

watch(activeUtteranceIndex, async (index, prev) => {
  if (index < 0 || index === prev) return
  await nextTick()
  utteranceRefs.value[index]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
})

watch([selectedFile, backendReady], ([file, ready]) => {
  if (!file || !ready || isTranscribing.value || !autoStartRequested.value) return
  autoStartRequested.value = false
  void startTranscription()
})

watch(
  speakerNames,
  () => {
    if (isHydratingRecord.value || !result.value || isTranscribing.value || !currentRecordId.value) return
    clearSpeakerNameSaveTimer()
    speakerNameSaveTimer = window.setTimeout(() => {
      void persistCurrentMinutes(true)
    }, 600)
  },
  { deep: true },
)
</script>

<template>
  <div class="detail-content">
    <div class="detail-header">
      <div class="detail-title">
        <h1 class="detail-heading">{{ meetingTitle }}</h1>
        <div class="detail-meta">
          <span>{{ recordedAtLabel }}</span>
          <span v-if="visibleSourceFileName">{{ visibleSourceFileName }}</span>
          <span class="status-badge" :class="`status-${statusBadge.tone}`">{{ statusBadge.label }}</span>
          <span v-if="hasResult" class="save-badge">{{ saveStatusLabel }}</span>
        </div>
      </div>

      <div class="header-actions">
        <button class="action-button button-secondary" :disabled="!hasResult || isSaving" @click="persistCurrentMinutes()">
          保存
        </button>
        <label class="action-button button-secondary">
          ファイルを選択
          <input
            class="hidden-input"
            type="file"
            accept=".mp4,.mp3,.wav,.m4a,.webm,.ogg,.flac"
            :disabled="!backendReady || isTranscribing"
            @change="onFileInput"
          />
        </label>
      </div>
    </div>

    <div v-if="errorMessage" class="page-banner banner-danger">{{ errorMessage }}</div>
    <div v-else-if="!backendReady" class="page-banner banner-warning">
      バックエンドの起動を待っています。起動後、ファイル選択やドロップで自動的に議事録作成を開始します。
    </div>

    <div class="content-section">
      <div class="summary-card">
        <div class="card-header">
          <h2 class="card-title"><span>📝</span> 要約・情報</h2>
          <div class="summary-actions">
            <button class="action-button button-ghost button-sm" :disabled="!hasResult" @click="copyToClipboard">
              コピー
            </button>
          </div>
        </div>
        <div class="summary-content">
          <label
            class="drop-zone"
            :class="{ drag: isDragOver, disabled: !backendReady || isTranscribing }"
            @drop.prevent="handleDrop"
            @dragover="handleDragOver"
            @dragleave="handleDragLeave"
          >
            <input
              class="hidden-input"
              type="file"
              accept=".mp4,.mp3,.wav,.m4a,.webm,.ogg,.flac"
              :disabled="!backendReady || isTranscribing"
              @change="onFileInput"
            />
            <div class="drop-content">
              <p v-if="!selectedFile" class="drop-title">音声・動画ファイルをドロップ</p>
              <p v-else class="drop-title">{{ selectedFile.name }}</p>
              <p class="drop-subtitle">対応形式: mp4 / mp3 / wav / m4a ... 選択後、自動で開始します。</p>
            </div>
          </label>

          <div v-if="isTranscribing" class="progress-container">
            <div class="flex-between">
              <span class="text-sm text-gray-600">{{ progressMessage }}</span>
              <span class="text-sm font-bold">{{ progress }}%</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: `${progress}%` }" />
            </div>
            <p v-if="processingTime !== null" class="text-xs text-gray-500 mt-2">経過時間: {{ formatProcessingTime(processingTime) }}</p>
          </div>

          <div v-if="hasResult" class="simple-summary prose">
            <p>
              <strong>ファイル:</strong>
              {{ visibleSourceFileName || '--' }}
              <template v-if="selectedFile">({{ formatBytes(selectedFile.size) }})</template>
            </p>
            <p><strong>収録時間:</strong> {{ result ? formatTime(result.audio_duration) : '--' }}</p>
            <p><strong>処理時間:</strong> {{ processingTime !== null ? formatProcessingTime(processingTime) : '--' }}</p>
            <p><strong>発話数:</strong> {{ utterances.length }} 件</p>
            <p><strong>話者数:</strong> {{ speakerSummaries.length }} 名</p>

            <hr class="my-4" />

            <h3>検出された話者</h3>
            <ul class="speaker-simple-list">
              <li v-for="speaker in speakerSummaries" :key="speaker.id">
                <div class="speaker-simple-row">
                  <span class="speaker-dot" :style="{ backgroundColor: speaker.color }"></span>
                  <div class="speaker-simple-meta">
                    <strong>{{ speaker.id }}</strong>
                    <span>{{ speaker.count }}発話 ({{ formatTime(speaker.duration) }})</span>
                  </div>
                </div>
                <input
                  class="speaker-name-input"
                  type="text"
                  :value="speakerNames[speaker.id] ?? ''"
                  :placeholder="`${speaker.id} の表示名`"
                  @input="onSpeakerNameInput(speaker.id, $event)"
                />
              </li>
            </ul>
          </div>
          <div v-else-if="!isTranscribing" class="empty-text">ここにファイル情報や文字起こしのサマリーが表示されます。</div>

          <div class="saved-section">
            <div class="saved-header">
              <h3 class="saved-title">保存済み議事録</h3>
              <span class="saved-count">{{ savedMinutes.length }}件</span>
            </div>
            <div v-if="savedMinutes.length === 0" class="saved-empty">まだ保存された議事録はありません。</div>
            <div v-else class="saved-list">
              <article
                v-for="record in savedMinutes"
                :key="record.id"
                class="saved-item"
                :class="{ active: record.id === currentRecordId, loading: isLoadingSaved && record.id === currentRecordId }"
              >
                <button class="saved-main" @click="loadSavedRecord(record)">
                  <strong class="saved-item-title">{{ record.title }}</strong>
                  <span class="saved-item-meta">{{ record.sourceFileName }}</span>
                  <span class="saved-item-meta">{{ dateTimeFormatter.format(new Date(record.savedAt)) }}</span>
                </button>
                <button class="saved-delete" @click="removeSavedRecord(record)">削除</button>
              </article>
            </div>
          </div>
        </div>
      </div>

      <div class="content-right">
        <div class="media-player-container">
          <div v-if="hasMedia">
            <video
              v-if="isVideoFile"
              ref="mediaElement"
              class="media-player"
              :src="mediaUrl"
              controls
              playsinline
              @timeupdate="onMediaTimeUpdate"
            />
            <audio
              v-else
              ref="mediaElement"
              class="media-player audio-player"
              :src="mediaUrl"
              controls
              playsinline
              @timeupdate="onMediaTimeUpdate"
            />
          </div>
          <div v-else class="media-empty">
            <p>保存済み議事録では文字起こし内容のみ再表示します。</p>
          </div>
        </div>

        <div class="transcript-container">
          <h2 class="transcript-header"><span class="header-icon">💬</span> 文字起こし</h2>
          <div class="transcript-body">
            <div v-if="!hasResult" class="text-gray-500 p-4">アップロード後、話者分離付き文字起こし結果がここに表示されます。</div>
            <template v-else>
              <div
                v-for="(utt, idx) in utterances"
                :key="`${utt.speaker_id}-${utt.start}-${idx}`"
                :ref="(el) => setUtteranceRef(el, idx)"
                class="transcript-segment"
                :class="{ active: idx === activeUtteranceIndex }"
                @click="seekTo(utt.start)"
              >
                <span class="timestamp-btn" :class="{ active: idx === activeUtteranceIndex }">
                  {{ formatTime(utt.start) }}~{{ formatTime(utt.end) }}
                </span>
                <span class="speaker-name" :style="{ color: speakerColorMap[utt.speaker_id] }">[{{ displaySpeakerName(utt.speaker_id) }}]</span>
                <span class="segment-text">{{ utt.text }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.detail-content {
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  padding: 1.5rem 2rem;
  overflow: hidden;
  color: #1a1a1a;
}

.detail-header {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  flex-shrink: 0;
}

@media (min-width: 768px) {
  .detail-header {
    flex-direction: row;
  }
}

.detail-title {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.detail-heading {
  font-size: 1.75rem;
  font-weight: 700;
  color: #111827;
  margin: 0;
  line-height: 1.2;
}

.detail-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.875rem;
  color: #6b7280;
}

.status-badge,
.save-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.125rem 0.625rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
}

.status-success {
  background: #dcfce7;
  color: #166534;
}

.status-warning {
  background: #fef9c3;
  color: #92400e;
}

.status-danger {
  background: #fee2e2;
  color: #991b1b;
}

.status-info {
  background: #dbeafe;
  color: #1e40af;
}

.status-neutral {
  background: #f3f4f6;
  color: #374151;
}

.save-badge {
  background: #eef4e2;
  color: #4f6b1f;
}

.header-actions,
.summary-actions {
  display: flex;
  gap: 0.5rem;
}

.action-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.action-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.button-secondary {
  background-color: white;
  color: #374151;
  border-color: #d1d5db;
}

.button-secondary:hover:not(:disabled) {
  background-color: #f9fafb;
}

.button-ghost {
  background-color: transparent;
  color: #4b5563;
}

.button-ghost:hover:not(:disabled) {
  background-color: #f3f4f6;
}

.button-sm {
  padding: 0.25rem 0.75rem;
  font-size: 0.75rem;
}

.hidden-input {
  display: none;
}

.page-banner {
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  flex-shrink: 0;
}

.banner-danger {
  background: #fee2e2;
  color: #991b1b;
}

.banner-warning {
  background: #fef9c3;
  color: #92400e;
}

.content-section {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  flex: 1;
  min-height: 0;
}

@media (min-width: 1024px) {
  .content-section {
    flex-direction: row;
  }
}

.summary-card {
  background-color: white;
  border-radius: 1rem;
  padding: 1.5rem;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  border: 1px solid #f3f4f6;
  display: flex;
  flex-direction: column;
  width: 100%;
}

@media (min-width: 1024px) {
  .summary-card {
    flex: 1;
    max-width: 420px;
  }
}

.card-header,
.saved-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
}

.card-header {
  margin-bottom: 1rem;
  flex-shrink: 0;
}

.card-title,
.saved-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #111827;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
}

.saved-title {
  font-size: 1rem;
}

.saved-count {
  font-size: 0.75rem;
  color: #6b7280;
}

.summary-content {
  color: #374151;
  flex: 1;
  overflow-y: auto;
}

.drop-zone {
  display: block;
  border: 2px dashed #e5e7eb;
  border-radius: 0.75rem;
  padding: 1.5rem;
  text-align: center;
  background-color: #f9fafb;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 1.5rem;
}

.drop-zone.drag {
  border-color: #8fa953;
  background-color: #f7faf1;
}

.drop-zone.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.drop-title {
  font-weight: 600;
  color: #111827;
  margin: 0 0 0.25rem 0;
}

.drop-subtitle {
  font-size: 0.75rem;
  color: #6b7280;
  margin: 0;
}

.progress-container {
  background: #f9fafb;
  padding: 1rem;
  border-radius: 0.5rem;
  margin-bottom: 1.5rem;
  border: 1px solid #f3f4f6;
}

.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.text-sm {
  font-size: 0.875rem;
}

.text-xs {
  font-size: 0.75rem;
}

.text-gray-600 {
  color: #4b5563;
}

.text-gray-500 {
  color: #6b7280;
}

.font-bold {
  font-weight: 700;
}

.mt-2 {
  margin-top: 0.5rem;
}

.progress-bar {
  margin-top: 0.5rem;
  height: 0.5rem;
  background-color: #e5e7eb;
  border-radius: 9999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background-color: #8fa953;
  transition: width 0.3s ease;
}

.simple-summary {
  font-size: 0.9rem;
  line-height: 1.6;
}

.simple-summary p {
  margin: 0.25rem 0;
}

.my-4 {
  margin-top: 1rem;
  margin-bottom: 1rem;
  border: 0;
  border-top: 1px solid #e5e7eb;
}

.simple-summary h3 {
  font-size: 1rem;
  font-weight: 600;
  margin: 0 0 0.5rem 0;
}

.speaker-simple-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.speaker-simple-list li {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.speaker-simple-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.speaker-simple-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.4rem;
}

.speaker-dot {
  width: 0.75rem;
  height: 0.75rem;
  border-radius: 9999px;
  display: inline-block;
}

.speaker-name-input {
  width: 100%;
  border: 1px solid #d1d5db;
  border-radius: 0.5rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  color: #1f2937;
  background: #fff;
}

.speaker-name-input:focus {
  outline: none;
  border-color: #8fa953;
  box-shadow: 0 0 0 3px rgba(143, 169, 83, 0.16);
}

.empty-text,
.saved-empty {
  color: #6b7280;
  font-size: 0.875rem;
}

.saved-section {
  margin-top: 1.5rem;
  padding-top: 1rem;
  border-top: 1px solid #e5e7eb;
}

.saved-list {
  margin-top: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.saved-item {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.5rem;
  align-items: stretch;
  padding: 0.5rem;
  border: 1px solid #e5e7eb;
  border-radius: 0.75rem;
  background: #fafaf8;
}

.saved-item.active {
  border-color: #8fa953;
  background: #f7faf1;
}

.saved-item.loading {
  opacity: 0.7;
}

.saved-main,
.saved-delete {
  border: 0;
  background: transparent;
  cursor: pointer;
}

.saved-main {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.2rem;
  text-align: left;
  color: inherit;
}

.saved-item-title {
  font-size: 0.9rem;
  color: #111827;
}

.saved-item-meta {
  font-size: 0.75rem;
  color: #6b7280;
}

.saved-delete {
  align-self: center;
  color: #b91c1c;
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
}

.saved-delete:hover {
  background: #fee2e2;
}

.content-right {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  width: 100%;
  min-height: 0;
}

@media (min-width: 1024px) {
  .content-right {
    flex: 1;
  }
}

.media-player-container {
  width: 100%;
  border-radius: 0.75rem;
  overflow: hidden;
  background-color: rgba(0, 0, 0, 0.05);
  border: 1px solid #e5e7eb;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  flex-shrink: 0;
}

.media-player {
  width: 100%;
  height: auto;
  max-height: 300px;
  object-fit: contain;
  display: block;
}

.audio-player {
  height: 54px;
}

.media-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  padding: 1rem;
  color: #6b7280;
  font-size: 0.875rem;
  text-align: center;
}

.transcript-container {
  background-color: white;
  border-radius: 1rem;
  padding: 1.5rem;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  border: 1px solid #f3f4f6;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.transcript-header {
  font-size: 1.25rem;
  font-weight: 700;
  color: #111827;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 1rem 0;
  flex-shrink: 0;
}

.header-icon {
  display: inline-block;
}

.transcript-body {
  white-space: pre-wrap;
  color: #374151;
  line-height: 1.7;
  font-size: 0.875rem;
  background-color: #f9fafb;
  padding: 1rem;
  border-radius: 0.75rem;
  overflow-y: auto;
  flex: 1;
}

.transcript-segment {
  margin-bottom: 0.5rem;
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
  transition: background-color 0.2s;
  cursor: pointer;
}

.transcript-segment:hover {
  background-color: #f3f4f6;
}

.transcript-segment.active {
  background-color: #eef4e2;
}

.timestamp-btn {
  display: inline-block;
  padding: 0.125rem 0.375rem;
  background-color: white;
  border: 1px solid #e5e7eb;
  border-radius: 0.25rem;
  color: #6b7280;
  font-size: 0.75rem;
  margin-right: 0.5rem;
  font-family: monospace;
}

.timestamp-btn.active {
  background-color: #8fa953;
  color: white;
  border-color: #8fa953;
}

.speaker-name {
  font-weight: 700;
  margin-right: 0.5rem;
}

.segment-text {
  color: #1f2937;
}
</style>
