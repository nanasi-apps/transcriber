<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
const progress = ref(0)
const progressStage = ref('')
const progressMessage = ref('Starting...')
const processingTime = ref<number | null>(null)
const mediaUrl = ref('')
const currentTime = ref(0)
const utteranceRefs = ref<HTMLElement[]>([])
const mediaElement = ref<HTMLMediaElement | null>(null)

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

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatProcessingTime(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}m ${s.toFixed(1)}s`
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
  result.value = null
  errorMessage.value = ''
  currentTime.value = 0
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
    .map((u) => `[${u.speaker_id}] (${formatTime(u.start)} - ${formatTime(u.end)})\n${u.text}`)
    .join('\n\n')
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

function setUtteranceRef(element: Element | null, index: number): void {
  if (!element) return
  utteranceRefs.value[index] = element as HTMLElement
}

watch(utterances, () => {
  utteranceRefs.value = []
})

watch(activeUtteranceIndex, async (index, prev) => {
  if (index < 0 || index === prev) return
  await nextTick()
  utteranceRefs.value[index]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
})
</script>

<template>
  <div class="shell">
    <section class="uploader-card">
      <div class="hero-copy">
        <p class="eyebrow">Transcriber</p>
        <h1>音声ファイルをアップロードするだけ</h1>
        <p class="lede">話者分離付き文字起こし結果を、そのまま見やすいビューで確認できます。</p>
      </div>

      <div v-if="!backendReady" class="status-pill status-wait">Starting backend...</div>
      <div v-else class="status-pill status-ready">Ready</div>

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
          <p v-if="!selectedFile" class="drop-title">ファイルを選択またはドロップ</p>
          <p v-else class="drop-title">{{ selectedFile.name }}</p>
          <p class="drop-subtitle">対応形式: mp4 / mp3 / wav / m4a / webm / ogg / flac</p>
        </div>
      </label>

      <button
        class="primary"
        :disabled="!selectedFile || !backendReady || isTranscribing"
        @click="startTranscription"
      >
        {{ isTranscribing ? 'Transcribing...' : 'Upload And Transcribe' }}
      </button>

      <div v-if="isTranscribing" class="progress-wrap">
        <div class="progress-meta">
          <span>{{ progressMessage }}</span>
          <span>{{ progress }}%</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: `${progress}%` }" />
        </div>
        <div v-if="processingTime !== null" class="progress-timing">
          Processing time: {{ formatProcessingTime(processingTime) }}
        </div>
      </div>

      <div v-if="errorMessage" class="notice error">{{ errorMessage }}</div>

      <!-- Summary after transcription -->
      <div v-if="hasResult && result" class="notice info">
        {{ utterances.length }} utterances
        &middot; {{ Object.keys(speakerColorMap).length }} speakers
        &middot; {{ formatTime(result.audio_duration) }} total
        <span v-if="processingTime !== null">&middot; Processing time {{ formatProcessingTime(processingTime) }}</span>
        <span v-if="timingValue('asr') !== null">&middot; ASR {{ formatProcessingTime(timingValue('asr')!) }}</span>
        <span v-if="timingValue('diarization') !== null">&middot; Diarization {{ formatProcessingTime(timingValue('diarization')!) }}</span>
        <span v-if="timingValue('alignment') !== null && timingValue('alignment')! > 0">&middot; Alignment {{ formatProcessingTime(timingValue('alignment')!) }}</span>
      </div>
    </section>

    <section class="viewer-card">
      <div class="viewer-header">
        <div>
          <p class="eyebrow">Result Viewer</p>
          <h2>Transcript</h2>
        </div>
        <button class="ghost" :disabled="!hasResult" @click="copyToClipboard">Copy</button>
      </div>

      <div v-if="hasMedia" class="player-shell">
        <div class="player-meta">
          <span>{{ selectedFile?.name }}</span>
          <span>{{ formatTime(currentTime) }} / {{ result ? formatTime(result.audio_duration) : '--:--' }}</span>
        </div>
        <video
          v-if="isVideoFile"
          ref="mediaElement"
          class="media-player"
          :src="mediaUrl"
          controls
          preload="metadata"
          @timeupdate="onMediaTimeUpdate"
        />
        <audio
          v-else
          ref="mediaElement"
          class="media-player audio-player"
          :src="mediaUrl"
          controls
          preload="metadata"
          @timeupdate="onMediaTimeUpdate"
        />
      </div>

      <div v-if="!hasResult" class="empty-state">
        アップロード後、話者分離付き文字起こし結果がここに表示されます。
      </div>

      <div v-else class="transcript-list">
        <article
          v-for="(utt, idx) in utterances"
          :key="idx"
          :ref="(el) => setUtteranceRef(el, idx)"
          class="segment-card"
          :class="{ active: idx === activeUtteranceIndex, clickable: hasMedia }"
          @click="seekTo(utt.start)"
        >
          <div class="segment-meta">
            <span
              class="speaker-badge"
              :style="{ background: speakerColorMap[utt.speaker_id] }"
            >
              {{ utt.speaker_id }}
            </span>
            <span class="timestamp">{{ formatTime(utt.start) }} - {{ formatTime(utt.end) }}</span>
          </div>
          <p class="segment-text">{{ utt.text }}</p>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100%;
  display: grid;
  grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
  gap: 1rem;
  padding: 1rem;
}

.uploader-card,
.viewer-card {
  background: rgba(255, 255, 255, 0.76);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.75);
  border-radius: 28px;
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.08);
}

.uploader-card {
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.viewer-card {
  padding: 1.5rem;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.player-shell {
  margin-bottom: 1rem;
  padding: 0.85rem;
  border-radius: 22px;
  background: linear-gradient(180deg, rgba(226, 232, 240, 0.45), rgba(248, 250, 252, 0.9));
  border: 1px solid rgba(148, 163, 184, 0.25);
}

.player-meta {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.65rem;
  font-size: 0.8rem;
  color: #475569;
  font-variant-numeric: tabular-nums;
}

.media-player {
  width: 100%;
  border-radius: 18px;
  background: #0f172a;
}

.audio-player {
  min-height: 56px;
}

.eyebrow {
  font-size: 0.72rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #64748b;
}

.hero-copy h1,
.viewer-header h2 {
  margin-top: 0.35rem;
  font-size: 1.85rem;
  line-height: 1.08;
  color: #0f172a;
}

.lede {
  margin-top: 0.65rem;
  color: #475569;
  line-height: 1.65;
}

.status-pill {
  display: inline-flex;
  width: fit-content;
  padding: 0.38rem 0.7rem;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 700;
}

.status-wait {
  background: #fef3c7;
  color: #92400e;
}

.status-ready {
  background: #dcfce7;
  color: #166534;
}

.drop-zone {
  display: block;
  border: 1.5px dashed #cbd5e1;
  border-radius: 24px;
  padding: 1.2rem;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(241, 245, 249, 0.85));
  cursor: pointer;
  transition:
    transform 0.2s ease,
    border-color 0.2s ease,
    background 0.2s ease;
}

.drop-zone.drag {
  border-color: #2563eb;
  background: linear-gradient(180deg, #eff6ff, #dbeafe);
  transform: translateY(-2px);
}

.drop-zone.disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.hidden-input {
  display: none;
}

.drop-content {
  min-height: 150px;
  display: grid;
  place-items: center;
  text-align: center;
}

.drop-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: #0f172a;
}

.drop-subtitle {
  margin-top: 0.55rem;
  color: #64748b;
  line-height: 1.5;
}

.primary,
.ghost {
  border: none;
  border-radius: 16px;
  font: inherit;
  cursor: pointer;
}

.primary {
  padding: 0.95rem 1rem;
  background: linear-gradient(135deg, #0f172a, #2563eb);
  color: #fff;
  font-weight: 700;
}

.primary:disabled,
.ghost:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.ghost {
  padding: 0.55rem 0.9rem;
  background: #eef2ff;
  color: #3730a3;
  font-weight: 600;
}

.progress-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.progress-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.82rem;
  color: #475569;
}

.progress-bar {
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #22c55e);
  transition: width 0.25s ease;
}

.progress-timing {
  font-size: 0.78rem;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}

.notice {
  padding: 0.85rem 1rem;
  border-radius: 16px;
  font-size: 0.85rem;
}

.error {
  background: #fef2f2;
  color: #b91c1c;
}

.info {
  background: #eff6ff;
  color: #1e40af;
}

.viewer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.empty-state {
  border: 1px dashed #cbd5e1;
  border-radius: 22px;
  padding: 2rem;
  color: #64748b;
}

.transcript-list {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  overflow: auto;
  min-height: 0;
}

.segment-card {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding: 0.85rem 1rem;
  border-radius: 20px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.92);
  transition:
    border-color 0.2s ease,
    background 0.2s ease,
    transform 0.2s ease,
    box-shadow 0.2s ease;
}

.segment-card.clickable {
  cursor: pointer;
}

.segment-card.clickable:hover {
  transform: translateY(-1px);
  border-color: #bfdbfe;
}

.segment-card.active {
  border-color: #2563eb;
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.98), rgba(219, 234, 254, 0.94));
  box-shadow: 0 14px 30px rgba(37, 99, 235, 0.12);
}

.segment-meta {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.speaker-badge {
  display: inline-flex;
  padding: 0.22rem 0.6rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.03em;
}

.timestamp {
  font-size: 0.75rem;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
}

.segment-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.9;
  font-size: 1rem;
  color: #111827;
}

@media (max-width: 900px) {
  .shell {
    grid-template-columns: 1fr;
  }
}
</style>
