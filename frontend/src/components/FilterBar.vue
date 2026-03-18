<template>
  <div class="filter-bar">
    <div class="flex flex-wrap items-center gap-3">
      <!-- Edition Dropdown -->
      <div class="flex-grow sm:flex-grow-0">
        <label class="block text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-1 ml-1">Edition</label>
        <div class="relative min-w-[180px]">
          <select
            v-model="filtersStore.selectedEditionId"
            class="input-field appearance-none pr-10 py-2.5 text-sm font-semibold text-gray-700"
          >
            <option v-for="ed in filtersStore.editions" :key="ed.id" :value="ed.id">
              {{ ed.display_name }}
            </option>
          </select>
          <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-3 text-gray-400">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
      </div>

      <!-- Date Picker -->
      <div class="flex-grow sm:flex-grow-0">
        <label class="block text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-1 ml-1">Date</label>
        <div class="relative">
          <input
            type="date"
            v-model="selectedDate"
            class="input-field py-2.5 text-sm font-semibold text-gray-700 min-w-[160px]"
          />
        </div>
      </div>

      <!-- Download PDF Button -->
      <div class="flex-grow sm:flex-grow-0 flex items-end">
        <div class="mb-0">
          <label class="block text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-1 ml-1">Export</label>
          <button
            @click="downloadPdf"
            :disabled="pdfLoading || !selectedEdition"
            class="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-bold text-white transition-all
                   bg-red-600 hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
          >
            <svg v-if="pdfLoading" class="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h6l2 2h4a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
            </svg>
            {{ pdfLoading ? 'Generating…' : 'Download PDF' }}
          </button>
          <p v-if="pdfError" class="text-[10px] text-red-500 mt-1 ml-1">{{ pdfError }}</p>
        </div>
      </div>

      <!-- Classified Image Button -->
      <div class="flex-grow sm:flex-grow-0 flex items-end">
        <div class="mb-0">
          <label class="block text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-1 ml-1">வரி படங்கள்</label>
          <button
            @click="showClassifiedImages"
            :disabled="imgLoading || !selectedEdition"
            class="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-bold text-white transition-all
                   bg-violet-600 hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
          >
            <svg v-if="imgLoading" class="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
            </svg>
            {{ imgLoading ? 'Loading…' : 'Classified Image' }}
          </button>
          <p v-if="imgError" class="text-[10px] text-red-500 mt-1 ml-1">{{ imgError }}</p>
        </div>
      </div>

      <!-- From URL -->
      <div class="flex-grow sm:flex-grow-0 flex items-end">
        <div class="mb-0">
          <label class="block text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-1 ml-1">From URL</label>
          <div class="flex gap-1">
            <input
              v-model="articleViewUrl"
              type="text"
              placeholder="ArticleView?eid=251&edate=16/03/2026"
              class="input-field py-2 text-xs font-medium text-gray-700 min-w-[240px] placeholder-gray-300"
              @keyup.enter="openFromUrl"
            />
            <button
              @click="openFromUrl"
              :disabled="!articleViewUrl.trim()"
              class="flex items-center px-3 py-2 rounded-xl text-sm font-bold text-white transition-all
                     bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
              title="Open classified viewer for this page URL"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/>
              </svg>
            </button>
          </div>
          <p v-if="urlError" class="text-[10px] text-red-500 mt-1 ml-1">{{ urlError }}</p>
        </div>
      </div>

      <!-- Scrape All Editions -->
      <div class="flex-grow sm:flex-grow-0 flex items-end">
        <div class="mb-0">
          <label class="block text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-1 ml-1">E-Scrapping</label>
          <button
            @click="openAllEditions"
            class="scrape-all-btn"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
            </svg>
            Scrape All Editions
          </button>
        </div>
      </div>

      <!-- Loading indicator -->
      <div class="flex-grow flex justify-end items-end">
        <div v-if="articlesStore.loading" class="flex items-center gap-2 text-brand-500 mb-0.5">
          <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
          <span class="text-xs font-bold uppercase tracking-widest">Refreshing</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filter-bar {
  background: linear-gradient(135deg, rgba(255,255,255,0.85) 0%, rgba(241,245,249,0.9) 100%);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(226,232,240,0.7);
  border-radius: 16px;
  padding: 16px 20px;
  margin-bottom: 24px;
  box-shadow: 0 4px 20px rgba(15,23,42,0.06), 0 1px 4px rgba(15,23,42,0.04);
}

.scrape-all-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border-radius: 10px;
  border: none;
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #f59e0b, #ef4444, #ec4899);
  background-size: 200% 200%;
  transition: opacity 0.2s, transform 0.15s;
  box-shadow: 0 2px 10px rgba(239,68,68,0.35);
  white-space: nowrap;
}
.scrape-all-btn:hover {
  opacity: 0.92;
  transform: translateY(-1px);
}
</style>

<script setup>
import { ref, computed, watch } from 'vue'
import { useFiltersStore } from '@/stores/filters'
import { useArticlesStore } from '@/stores/articles'
import api from '@/services/api'

const filtersStore = useFiltersStore()
const articlesStore = useArticlesStore()

const _now = new Date()
const selectedDate = ref(
  [
    _now.getFullYear(),
    String(_now.getMonth() + 1).padStart(2, '0'),
    String(_now.getDate()).padStart(2, '0'),
  ].join('-')
)
const pdfLoading = ref(false)
const pdfError   = ref('')

// Classified Image viewer state
const imgLoading = ref(false)
const imgError   = ref('')

// From-URL viewer state
const articleViewUrl = ref('')
const urlError       = ref('')

const selectedEdition = computed(() =>
  filtersStore.editions.find(e => e.id === filtersStore.selectedEditionId) || null
)

watch(selectedDate, (newVal) => {
  filtersStore.setDate(newVal)
}, { immediate: true })

function _triggerDownload(blobUrl, filename) {
  const link = document.createElement('a')
  link.href  = blobUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(blobUrl)
}

function _b64ToBlob(dataUri) {
  const [meta, b64] = dataUri.split(',')
  const mime = (meta.match(/:(.*?);/) || [])[1] || 'image/jpeg'
  const bytes = atob(b64)
  const arr = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i)
  return { blob: new Blob([arr], { type: mime }), ext: mime.includes('png') ? 'png' : 'jpg' }
}

// ── From-URL: open viewer for a specific ArticleView URL ─────────────────────
function openFromUrl() {
  urlError.value = ''
  const raw = articleViewUrl.value.trim()
  if (!raw) return

  try {
    // Accept both full URL and bare query string
    const urlToParse = raw.startsWith('http') ? raw : `https://epaper.dailythanthi.com/Home/ArticleView${raw.startsWith('?') ? '' : '?'}${raw}`
    const parsed = new URL(urlToParse)
    const pgid  = parsed.searchParams.get('pgid')  || parsed.searchParams.get('Pgid')  || ''
    const eid   = parsed.searchParams.get('eid')   || ''
    const edate = parsed.searchParams.get('edate') || ''

    if (!pgid && !eid) {
      urlError.value = 'Could not find pgid or eid in URL'
      return
    }

    const cityCode = selectedEdition.value?.city_code || ''
    const date     = selectedDate.value
    const base = import.meta.env.VITE_API_BASE_URL
      ? import.meta.env.VITE_API_BASE_URL.replace('/api', '')
      : ''
    const params = new URLSearchParams()
    if (pgid)     params.set('pgid',        pgid)
    if (cityCode) params.set('edition',     cityCode)
    if (date)     params.set('date',        date)
    if (eid)      params.set('eid',         eid)
    if (edate)    params.set('edate',       edate)
    params.set('source_url', raw)
    window.open(`${base}/viewer/classifieds?${params}`, '_blank', 'noopener,noreferrer')
  } catch {
    urlError.value = 'Invalid URL'
  }
}

// ── Classified Image button — opens standalone viewer in new tab ──────────────
function showClassifiedImages() {
  const cityCode = selectedEdition.value?.city_code || ''
  const eid      = selectedEdition.value ? (api.CITY_CODE_TO_EID?.[cityCode] || '') : ''
  const date     = selectedDate.value
  // Opens viewer; user can paste ArticleView URL (with pgid) inside the viewer
  const url = api.classifiedsViewerUrl('', cityCode, date, eid)
  window.open(url, '_blank', 'noopener,noreferrer')
}

// ── Scrape All Editions ───────────────────────────────────────────────────────
function openAllEditions() {
  const base = import.meta.env.VITE_API_BASE_URL
    ? import.meta.env.VITE_API_BASE_URL.replace('/api', '')
    : window.location.origin
  window.open(base + '/viewer', '_blank')
}

// ── PDF download ──────────────────────────────────────────────────────────────
async function downloadPdf() {
  if (!selectedEdition.value) return
  pdfLoading.value = true
  pdfError.value   = ''

  try {
    const cityCode = selectedEdition.value.city_code
    const date     = selectedDate.value

    const response = await api.downloadEditionPdf(cityCode, date)
    const blob     = new Blob([response.data], { type: 'application/pdf' })
    const blobUrl  = URL.createObjectURL(blob)
    const link     = document.createElement('a')
    link.href      = blobUrl
    link.download  = `dailythanthi_${cityCode}_${date}.pdf`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(blobUrl)
  } catch (e) {
    pdfError.value = e?.response?.data
      ? 'Generation failed — check backend logs'
      : (e.message || 'Unknown error')
  } finally {
    pdfLoading.value = false
  }
}
</script>
