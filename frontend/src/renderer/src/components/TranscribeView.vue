<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  type ComponentPublicInstance,
  watch,
} from 'vue'
import {
  healthCheck,
  transcribeStatus,
  transcribeUpload,
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

const dateTimeFormatter = new Intl.DateTimeFormat('ja-JP', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

onMounted(async () => {
  for (let i = 0; i < 30; i++) {
    if (await healthCheck()) {
      backendReady.value = true
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  errorMessage.value = 'Backend server failed to start.'
})

const utterances = computed<Utterance[]>(() => result.value?.utterances ?? [])
const hasResult = computed(() => utterances.value.length > 0)
const hasMedia = computed(() => mediaUrl.value.length > 0)
const isVideoFile = computed(() => {
  if (!selectedFile.value) return false
  if (selectedFile.value.type.startsWith('video/')) return true
  return /\.(mp4|webm|mov|m4v)$/i.test(selectedFile.value.name)
})
const meetingTitle = computed(() => {
  if (!selectedFile.value) return '議事録ビュー'
  const baseName = selectedFile.value.name.replace(/\.[^.]+$/, '')
  return baseName || selectedFile.value.name
})
const recordedAtLabel = computed(() => {
  if (!selectedAt.value) return 'ローカルファイルを選択してください'
  return dateTimeFormatter.format(selectedAt.value)
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
})

// Assign a stable colour per speaker
const SPEAKER_COLORS = [
  '#2563eb', // blue
  '#dc2626', // red
  '#059669', // emerald
  '#d97706', // amber
  '#7c3aed', // violet
  '#db2777', // pink
  '#0891b2', // cyan
  '#65a30d', // lime
]

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

const summaryStats = computed(() => [
  {
    label: '発話数',
    value: hasResult.value ? String(utterances.value.length) : '--',
    hint: hasResult.value ? 'utterances' : '未生成',
  },
  {
    label: '話者数',
    value: hasResult.value ? String(speakerSummaries.value.length) : '--',
    hint: hasResult.value ? 'speakers' : '未生成',
  },
  {
    label: '収録時間',
    value: result.value ? formatTime(result.value.audio_duration) : '--',
    hint: result.value ? 'audio length' : 'ファイル待機中',
  },
  {
    label: '処理時間',
    value: processingTime.value !== null ? formatProcessingTime(processingTime.value) : '--',
    hint: processingTime.value !== null ? 'pipeline total' : '未計測',
  },
])
const fileFacts = computed(() => {
  if (!selectedFile.value) return []
  const extension = selectedFile.value.name.split('.').pop()?.toUpperCase() ?? 'UNKNOWN'
  return [
    { label: 'ファイル名', value: selectedFile.value.name },
    { label: '形式', value: selectedFile.value.type || extension },
    { label: 'サイズ', value: formatBytes(selectedFile.value.size) },
  ]
})
const processingSteps = computed(() => [
  { key: 'audio_prep', label: '音声準備', value: timingValue('audio_prep') },
  { key: 'asr', label: '文字起こし', value: timingValue('asr') },
  { key: 'diarization', label: '話者分離', value: timingValue('diarization') },
  { key: 'alignment', label: 'タイムライン補正', value: timingValue('alignment') },
  { key: 'merge', label: '表示用整形', value: timingValue('merge') },
])
const summaryHighlights = computed(() =>
  utterances.value
    .filter((utterance) => utterance.text.trim().length > 0)
    .slice(0, 4)
    .map((utterance, index) => ({
      id: `${utterance.speaker_id}-${utterance.start}-${index}`,
      speakerId: utterance.speaker_id,
      start: utterance.start,
      end: utterance.end,
      text: truncateText(utterance.text, 96),
    })),
)

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

function truncateText(text: string, maxLength: number): string {
  const compact = text.replace(/\s+/g, ' ').trim()
  if (compact.length <= maxLength) return compact
  return `${compact.slice(0, maxLength - 1)}...`
}

function timingValue(key: string): number | null {
  const value = stageTimings.value[key]
  return typeof value === 'number' ? value : null
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
</script>

<template>
  <div class="detail-content">
    <div class="detail-header">
      <div class="detail-title">
        <h1 class="detail-heading">{{ meetingTitle }}</h1>
        <div class="detail-meta">
          <span>{{ recordedAtLabel }}</span>
          <span v-if="selectedFile">{{ selectedFile.name }}</span>
          <span class="status-badge" :class="`status-${statusBadge.tone}`">{{
            statusBadge.label
          }}</span>
        </div>
      </div>

      <div class="header-actions">
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
      <!-- Left: Summary / Info Card (mimicking CF's SummaryCard.vue) -->
      <div class="summary-card">
        <div class="card-header">
          <h2 class="card-title"><span>📝</span> 要約・情報</h2>
          <button
            class="action-button button-ghost button-sm"
            :disabled="!hasResult"
            @click="copyToClipboard"
          >
            コピー
          </button>
        </div>
        <div class="summary-content">
          <!-- Dropzone -->
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

          <!-- Progress -->
          <div v-if="isTranscribing" class="progress-container">
            <div class="flex-between">
              <span class="text-sm text-gray-600">{{ progressMessage }}</span>
              <span class="text-sm font-bold">{{ progress }}%</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: `${progress}%` }" />
            </div>
            <p v-if="processingTime !== null" class="text-xs text-gray-500 mt-2">
              経過時間: {{ formatProcessingTime(processingTime) }}
            </p>
          </div>

          <!-- Simple Text Summary -->
          <div v-if="hasResult" class="simple-summary prose">
            <p>
              <strong>ファイル:</strong> {{ selectedFile?.name }} ({{
                selectedFile ? formatBytes(selectedFile.size) : ''
              }})
            </p>
            <p>
              <strong>収録時間:</strong> {{ result ? formatTime(result.audio_duration) : '--' }}
            </p>
            <p>
              <strong>処理時間:</strong>
              {{ processingTime !== null ? formatProcessingTime(processingTime) : '--' }}
            </p>
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
          <div v-else-if="!isTranscribing" class="empty-text">
            ここにファイル情報や文字起こしのサマリーが表示されます。
          </div>
        </div>
      </div>

      <!-- Right: Media and Transcript -->
      <div class="content-right">
        <!-- Media Player (mimicking CF's MediaPlayer.vue) -->
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
          <div v-else class="media-empty" aria-hidden="true"></div>
        </div>

        <!-- Transcript Card (mimicking CF's TranscriptCard.vue) -->
        <div class="transcript-container">
          <h2 class="transcript-header"><span class="header-icon">💬</span> 文字起こし</h2>
          <div class="transcript-body">
            <div v-if="!hasResult" class="text-gray-500 p-4">
              アップロード後、話者分離付き文字起こし結果がここに表示されます。
            </div>
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
                <span class="speaker-name" :style="{ color: speakerColorMap[utt.speaker_id] }"
                  >[{{ displaySpeakerName(utt.speaker_id) }}]</span
                >
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
/* App Layout */
.detail-content {
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  padding: 1.5rem 2rem;
  overflow: hidden;
  color: #1a1a1a;
}

/* Header (mimics detail-header in CF) */
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
  gap: 1rem;
  font-size: 0.875rem;
  color: #6b7280;
}

/* Status Badge */
.status-badge {
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

/* Buttons */
.header-actions {
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
.button-primary {
  background-color: #8fa953; /* CF mattya-500 */
  color: white;
}
.button-primary:hover:not(:disabled) {
  background-color: #738a3f; /* CF mattya-600 */
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

/* Page Banners */
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

/* Content Section (matches content-section in CF) */
.content-section {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  flex: 1;
  min-height: 0; /* Important for scroll */
}
@media (min-width: 1024px) {
  .content-section {
    flex-direction: row;
  }
}

/* Left: Summary Card (mimics CF SummaryCard) */
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
    max-width: 400px;
  }
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  flex-shrink: 0;
}

.card-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #111827;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
}

.summary-content {
  color: #374151;
  flex: 1;
  overflow-y: auto;
}

/* Dropzone in Summary */
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

/* Progress in Summary */
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
  background-color: #8fa953; /* CF mattya-500 */
  transition: width 0.3s ease;
}

/* Simple Summary Text */
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

.empty-text {
  color: #6b7280;
  font-size: 0.875rem;
}

/* Right: Content Right (mimics CF content-right) */
.content-right {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  width: 100%;
  min-height: 0; /* Important for scroll */
}
@media (min-width: 1024px) {
  .content-right {
    flex: 1; /* Takes remaining space */
  }
}

/* Media Player */
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
  display: none;
}

/* Transcript Card (mimics CF TranscriptCard) */
.transcript-container {
  background-color: white;
  border-radius: 1rem;
  padding: 1.5rem;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  border: 1px solid #f3f4f6;
  flex: 1; /* Fills remaining height */
  display: flex;
  flex-direction: column;
  min-height: 0; /* Important for scroll */
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
  background-color: #eef4e2; /* CF mattya-100 */
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
