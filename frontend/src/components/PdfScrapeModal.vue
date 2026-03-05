<template>
  <!-- Trigger Button -->
  <button @click="open = true" class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-brand-50 text-brand-600 hover:bg-brand-100 transition-colors">
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
    </svg>
    <span class="hidden sm:inline">Scrape</span>
  </button>

  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="closeModal"></div>

      <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-xl mx-auto z-10">

        <!-- Header -->
        <div class="flex items-center justify-between p-6 border-b border-gray-100">
          <div class="flex items-center gap-3">
            <div class="w-9 h-9 bg-brand-50 rounded-lg flex items-center justify-center">
              <svg class="w-5 h-5 text-brand-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div>
              <h2 class="text-lg font-bold text-gray-900">Scraper</h2>
              <p class="text-xs text-gray-500">Import content from PDFs or webpages</p>
            </div>
          </div>
          <button @click="closeModal" class="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Tabs -->
        <div class="flex border-b border-gray-100">
          <button
            @click="activeTab = 'pdf'; resetResult()"
            class="flex-1 py-3 text-sm font-semibold transition-colors"
            :class="activeTab === 'pdf' ? 'text-brand-600 border-b-2 border-brand-500' : 'text-gray-400 hover:text-gray-600'"
          >
            PDF Scraper
          </button>
          <button
            @click="activeTab = 'webpage'; resetResult()"
            class="flex-1 py-3 text-sm font-semibold transition-colors"
            :class="activeTab === 'webpage' ? 'text-brand-600 border-b-2 border-brand-500' : 'text-gray-400 hover:text-gray-600'"
          >
            Webpage → PDF
          </button>
          <button
            @click="activeTab = 'urltopdf'; resetResult()"
            class="flex-1 py-3 text-sm font-semibold transition-colors"
            :class="activeTab === 'urltopdf' ? 'text-brand-600 border-b-2 border-brand-500' : 'text-gray-400 hover:text-gray-600'"
          >
            URL → Export
          </button>
        </div>

        <!-- Body -->
        <div class="p-6 space-y-4">

          <!-- URL Input -->
          <div>
            <label class="block text-sm font-semibold text-gray-700 mb-1.5">URL</label>
            <input
              v-model="url"
              type="url"
              :placeholder="activeTab === 'pdf'
                ? 'https://example.com/report.pdf'
                : activeTab === 'webpage'
                  ? 'https://epaper.dailythanthi.com  (or a specific ArticleView URL)'
                  : 'https://epaper.dailythanthi.com  or any public webpage URL'"
              class="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent transition"
              :disabled="loading"
              @keydown.enter="submit"
            />
            <p class="text-xs text-gray-400 mt-1">
              <template v-if="activeTab === 'pdf'">Supports direct PDF links or webpages containing PDF links</template>
              <template v-else-if="activeTab === 'webpage'">Logs into Daily Thanthi epaper. Use the homepage URL to get today's full edition, or an ArticleView URL for a specific page.</template>
              <template v-else>Scrapes any public webpage (handles JS-rendered pages). Daily Thanthi URLs are auto-detected and handled with login.</template>
            </p>
          </div>

          <!-- Export Format Selector (shown for webpage + urltopdf tabs) -->
          <div v-if="activeTab !== 'pdf'">
            <label class="block text-sm font-semibold text-gray-700 mb-2">Export Format</label>
            <div class="flex gap-2">
              <!-- PDF -->
              <button
                @click="format = 'pdf'"
                :disabled="loading"
                class="flex-1 flex flex-col items-center gap-1.5 py-3 px-2 rounded-xl border-2 transition-all"
                :class="format === 'pdf'
                  ? 'border-brand-500 bg-brand-50 text-brand-700'
                  : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300'"
              >
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/>
                </svg>
                <span class="text-xs font-semibold">PDF</span>
                <span class="text-[10px] text-center leading-tight opacity-70">Download as<br>PDF document</span>
              </button>

              <!-- JSON -->
              <button
                @click="format = 'json'"
                :disabled="loading"
                class="flex-1 flex flex-col items-center gap-1.5 py-3 px-2 rounded-xl border-2 transition-all"
                :class="format === 'json'
                  ? 'border-brand-500 bg-brand-50 text-brand-700'
                  : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300'"
              >
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/>
                </svg>
                <span class="text-xs font-semibold">JSON</span>
                <span class="text-[10px] text-center leading-tight opacity-70">Structured<br>article data</span>
              </button>

              <!-- Screenshot -->
              <button
                @click="format = 'screenshot'"
                :disabled="loading"
                class="flex-1 flex flex-col items-center gap-1.5 py-3 px-2 rounded-xl border-2 transition-all"
                :class="format === 'screenshot'
                  ? 'border-brand-500 bg-brand-50 text-brand-700'
                  : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300'"
              >
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/>
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"/>
                </svg>
                <span class="text-xs font-semibold">Screenshot</span>
                <span class="text-[10px] text-center leading-tight opacity-70">Full-page<br>PNG image</span>
              </button>
            </div>
          </div>

          <!-- Error -->
          <div v-if="error" class="bg-red-50 border border-red-100 rounded-xl px-4 py-3 text-sm text-red-700">
            {{ error }}
          </div>

          <!-- PDF Scraper Results -->
          <div v-if="activeTab === 'pdf' && pdfResult" class="space-y-3">
            <div class="grid grid-cols-3 gap-3">
              <div class="bg-green-50 rounded-xl p-3 text-center">
                <div class="text-2xl font-bold text-green-600">{{ pdfResult.saved }}</div>
                <div class="text-xs text-green-700 font-medium mt-0.5">Saved</div>
              </div>
              <div class="bg-yellow-50 rounded-xl p-3 text-center">
                <div class="text-2xl font-bold text-yellow-600">{{ pdfResult.skipped }}</div>
                <div class="text-xs text-yellow-700 font-medium mt-0.5">Skipped</div>
              </div>
              <div class="bg-red-50 rounded-xl p-3 text-center">
                <div class="text-2xl font-bold text-red-600">{{ pdfResult.failed }}</div>
                <div class="text-xs text-red-700 font-medium mt-0.5">Failed</div>
              </div>
            </div>
            <div v-if="pdfResult.total_found === 0" class="text-center text-sm text-gray-500 py-2">
              No PDF links found at this URL.
            </div>
            <div v-else class="max-h-48 overflow-y-auto space-y-2 pr-1">
              <div
                v-for="item in pdfResult.results" :key="item.url"
                class="flex items-start gap-3 p-3 rounded-xl border text-sm"
                :class="{
                  'bg-green-50 border-green-100': item.status === 'saved',
                  'bg-yellow-50 border-yellow-100': item.status === 'skipped',
                  'bg-red-50 border-red-100': item.status === 'failed',
                }"
              >
                <span class="mt-0.5 text-lg">
                  {{ item.status === 'saved' ? '✅' : item.status === 'skipped' ? '⏭️' : '❌' }}
                </span>
                <div class="min-w-0 flex-1">
                  <p class="font-medium text-gray-800 truncate">{{ item.title || item.url }}</p>
                  <p class="text-xs text-gray-500 mt-0.5">{{ item.message }}</p>
                </div>
              </div>
            </div>
          </div>

          <!-- Success: PDF downloaded -->
          <div v-if="activeTab !== 'pdf' && exportSuccess && format === 'pdf'" class="bg-green-50 border border-green-100 rounded-xl px-4 py-4 text-sm text-green-800 flex items-center gap-3">
            <svg class="w-6 h-6 text-green-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>PDF downloaded successfully!</span>
          </div>

          <!-- Success: Screenshot downloaded -->
          <div v-if="activeTab !== 'pdf' && exportSuccess && format === 'screenshot'" class="space-y-3">
            <div class="bg-green-50 border border-green-100 rounded-xl px-4 py-3 text-sm text-green-800 flex items-center gap-3">
              <svg class="w-5 h-5 text-green-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Screenshot captured and downloaded!</span>
            </div>
            <img v-if="screenshotDataUrl" :src="screenshotDataUrl" alt="Page screenshot"
              class="w-full rounded-xl border border-gray-200 max-h-64 object-cover object-top cursor-pointer"
              @click="openScreenshot" />
          </div>

          <!-- Success: JSON result -->
          <div v-if="activeTab !== 'pdf' && exportSuccess && format === 'json'" class="space-y-3">
            <div class="flex items-center justify-between">
              <span class="text-sm font-semibold text-gray-700">
                {{ jsonResult?.articles?.length ?? jsonResult?.content_blocks?.length ?? 0 }} items extracted
              </span>
              <button @click="downloadJson" class="text-xs text-brand-600 hover:underline font-medium">
                Download JSON
              </button>
            </div>
            <pre class="bg-gray-50 border border-gray-200 rounded-xl p-3 text-xs text-gray-700 max-h-56 overflow-auto whitespace-pre-wrap break-all">{{ jsonPreview }}</pre>
          </div>

          <!-- Loading indicator -->
          <div v-if="loading" class="flex flex-col items-center gap-3 py-4 text-sm text-gray-500">
            <svg class="w-8 h-8 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <span>{{ loadingMessage }}</span>
          </div>

        </div>

        <!-- Footer -->
        <div class="flex items-center justify-between px-6 py-4 border-t border-gray-100 bg-gray-50 rounded-b-2xl">
          <button @click="closeModal" class="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
            {{ exportSuccess || pdfResult ? 'Close' : 'Cancel' }}
          </button>
          <button
            @click="submit"
            :disabled="loading || !url.trim()"
            class="flex items-center gap-2 px-5 py-2 bg-brand-600 text-white text-sm font-semibold rounded-xl hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <svg v-if="loading" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <span>{{ submitLabel }}</span>
          </button>
        </div>

      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed } from 'vue'
import api from '@/services/api'
import { useArticlesStore } from '@/stores/articles'
import { useFiltersStore } from '@/stores/filters'

const open           = ref(false)
const activeTab      = ref('pdf')
const format         = ref('pdf')   // 'pdf' | 'json' | 'screenshot'
const url            = ref('')
const loading        = ref(false)
const error          = ref('')
const pdfResult      = ref(null)
const exportSuccess  = ref(false)
const jsonResult     = ref(null)
const screenshotDataUrl = ref('')

const articlesStore = useArticlesStore()
const filtersStore  = useFiltersStore()

const loadingMessage = computed(() => {
  if (activeTab.value === 'pdf') return 'Scraping PDFs...'
  if (format.value === 'screenshot') return 'Rendering page and taking screenshot...'
  if (format.value === 'json') return 'Scraping page data...'
  return 'Logging in and generating PDF... this may take 1–3 minutes'
})

const submitLabel = computed(() => {
  if (loading.value) return loadingMessage.value
  if (activeTab.value === 'pdf') return 'Scrape'
  if (format.value === 'screenshot') return 'Take Screenshot'
  if (format.value === 'json') return 'Export JSON'
  return 'Download PDF'
})

const jsonPreview = computed(() => {
  if (!jsonResult.value) return ''
  return JSON.stringify(jsonResult.value, null, 2).slice(0, 2000) + (
    JSON.stringify(jsonResult.value).length > 2000 ? '\n... (truncated)' : ''
  )
})

function resetResult() {
  error.value          = ''
  pdfResult.value      = null
  exportSuccess.value  = false
  jsonResult.value     = null
  screenshotDataUrl.value = ''
}

function closeModal() {
  if (loading.value) return
  if (pdfResult.value?.saved > 0) {
    articlesStore.fetchArticles({
      edition_id: filtersStore.selectedEditionId,
      section_id: filtersStore.selectedSectionId,
      date: filtersStore.selectedDate,
    })
  }
  open.value = false
  url.value  = ''
  resetResult()
}

async function submit() {
  if (!url.value.trim() || loading.value) return
  loading.value = true
  resetResult()

  try {
    if (activeTab.value === 'pdf') {
      // ── PDF Scraper tab ─────────────────────────────────────────────────────
      const response = await api.scrapePdf(url.value.trim())
      pdfResult.value = response.data

    } else if (format.value === 'screenshot') {
      // ── Screenshot format ───────────────────────────────────────────────────
      const response = await api.scrapeScreenshot(url.value.trim())
      const blob = new Blob([response.data], { type: 'image/png' })
      // Show preview
      screenshotDataUrl.value = URL.createObjectURL(blob)
      // Auto-download
      _downloadBlob(blob, response, 'screenshot.png')
      exportSuccess.value = true

    } else if (format.value === 'json') {
      // ── JSON format ─────────────────────────────────────────────────────────
      const response = await api.scrapeJson(url.value.trim())
      jsonResult.value = response.data
      exportSuccess.value = true

    } else {
      // ── PDF format (webpage or url-to-pdf tab) ──────────────────────────────
      const fn = activeTab.value === 'webpage'
        ? () => api.scrapeWebpagePdf(url.value.trim())
        : () => api.scrapeUrlToPdf(url.value.trim())
      const response = await fn()
      _downloadBlob(new Blob([response.data], { type: 'application/pdf' }), response, 'page.pdf')
      exportSuccess.value = true
    }

  } catch (e) {
    // arraybuffer error responses need text decoding
    if (e.response?.data instanceof ArrayBuffer) {
      try {
        const json = JSON.parse(new TextDecoder().decode(e.response.data))
        error.value = json.detail || 'Something went wrong.'
      } catch {
        error.value = 'Something went wrong. Check the URL and try again.'
      }
    } else {
      error.value = e.response?.data?.detail || 'Something went wrong. Check the URL and try again.'
    }
  } finally {
    loading.value = false
  }
}

function _downloadBlob(blob, response, fallbackName) {
  const disposition = response.headers?.['content-disposition'] || ''
  const match = disposition.match(/filename="([^"]+)"/)
  const filename = match ? match[1] : fallbackName
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = filename
  link.click()
  URL.revokeObjectURL(link.href)
}

function openScreenshot() {
  if (screenshotDataUrl.value) window.open(screenshotDataUrl.value, '_blank')
}

function downloadJson() {
  if (!jsonResult.value) return
  const blob = new Blob([JSON.stringify(jsonResult.value, null, 2)], { type: 'application/json' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = 'scraped_data.json'
  link.click()
  URL.revokeObjectURL(link.href)
}
</script>
