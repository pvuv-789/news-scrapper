<template>
  <div class="home-page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">{{ filtersStore.currentEditionName }} News</h1>
        <p class="page-sub">Top stories curated from the Daily Thanthi E-Paper.</p>
      </div>
      <button class="pdf-upload-btn" @click="showPdfModal = true">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:16px;height:16px;flex-shrink:0">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
        </svg>
        Upload PDF
      </button>
    </div>

    <!-- PDF Upload Modal -->
    <Teleport to="body">
      <div v-if="showPdfModal" class="pdf-modal-backdrop" @click.self="closePdfModal">
        <div class="pdf-modal">
          <!-- Modal header -->
          <div class="pdf-modal-header">
            <span class="pdf-modal-title">PDF Content Extractor</span>
            <button class="pdf-modal-close" @click="closePdfModal">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:18px;height:18px">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>

          <!-- Drop zone -->
          <div
            class="pdf-drop-zone"
            :class="{ dragging: pdfDragging, 'has-file': !!pdfFile }"
            @dragover.prevent="pdfDragging = true"
            @dragleave.prevent="pdfDragging = false"
            @drop.prevent="onPdfDrop"
            @click="pdfFileInput.click()"
          >
            <input ref="pdfFileInput" type="file" accept=".pdf,application/pdf" style="display:none" @change="onPdfFileChange" />
            <template v-if="!pdfFile">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:40px;height:40px;color:#6366f1">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              <p class="drop-label">Drag & drop a PDF, or <span style="color:#6366f1;text-decoration:underline">browse</span></p>
              <p class="drop-hint">Only .pdf files supported</p>
            </template>
            <template v-else>
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:40px;height:40px;color:#10b981">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p class="drop-label">{{ pdfFile.name }}</p>
              <p class="drop-hint">{{ (pdfFile.size / 1024).toFixed(1) }} KB — click to change</p>
            </template>
          </div>

          <!-- Actions -->
          <div class="pdf-modal-actions">
            <button class="pdf-extract-btn" :disabled="!pdfFile || pdfLoading" @click="extractPdf">
              <svg v-if="pdfLoading" fill="none" stroke="currentColor" viewBox="0 0 24 24" class="pdf-spin">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
              </svg>
              {{ pdfLoading ? 'Extracting…' : 'Extract Content' }}
            </button>
            <button v-if="pdfResult" class="pdf-download-btn" @click="downloadPdfJson">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:15px;height:15px">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
              </svg>
              Download JSON
            </button>
          </div>

          <!-- Error -->
          <div v-if="pdfError" class="pdf-error-msg">{{ pdfError }}</div>

          <!-- Results -->
          <div v-if="pdfResult" class="pdf-results">
            <div class="pdf-result-meta">
              <span class="pdf-chip">{{ pdfResult.total_pages }} page{{ pdfResult.total_pages !== 1 ? 's' : '' }}</span>
              <span class="pdf-chip">{{ pdfResult.word_count.toLocaleString() }} words</span>
              <span class="pdf-chip">{{ pdfResult.char_count.toLocaleString() }} chars</span>
            </div>
            <div class="pdf-result-title">{{ pdfResult.title }}</div>
            <div class="pdf-pages">
              <div v-for="pg in pdfResult.pages" :key="pg.page" class="pdf-page-block">
                <div class="pdf-page-label">Page {{ pg.page }}</div>
                <pre class="pdf-page-text">{{ pg.text || '(no text on this page)' }}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Filters Section -->
    <FilterBar />

    <!-- Error State -->
    <div v-if="articlesStore.error" class="bg-red-50 border border-red-100 rounded-xl p-6 text-center">
      <div class="text-red-500 mb-2">
        <svg class="w-12 h-12 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <h3 class="text-lg font-bold text-red-800">Connection Error</h3>
      <p class="text-red-600 mb-4">{{ articlesStore.error }}</p>
      <button @click="reloadData" class="btn-primary">Try Again</button>
    </div>

    <!-- Loading State -->
    <div v-else-if="articlesStore.loading && articlesStore.articles.length === 0" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div v-for="n in 6" :key="n" class="bg-white border border-gray-100 rounded-2xl h-80 animate-pulse">
        <div class="h-40 bg-gray-50 rounded-t-2xl mb-4"></div>
        <div class="px-5 space-y-3">
          <div class="h-4 w-1/4 bg-gray-100 rounded"></div>
          <div class="h-6 w-3/4 bg-gray-100 rounded"></div>
          <div class="h-4 w-full bg-gray-100 rounded"></div>
          <div class="h-4 w-full bg-gray-100 rounded"></div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else-if="!articlesStore.loading && articlesStore.articles.length === 0" class="bg-white border border-gray-100 rounded-2xl p-16 text-center">
      <div class="text-gray-300 mb-4">
        <svg class="w-20 h-20 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10l4 4v10a2 2 0 01-2 2z" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M14 4v4h4" />
        </svg>
      </div>
      <h3 class="text-xl font-bold text-gray-900 mb-2">No Articles Found</h3>
      <p class="text-gray-500 max-w-md mx-auto">
        We couldn't find any news for the selected criteria. Try adjusting your filters or changing the date.
      </p>
    </div>

    <!-- Articles Grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <ArticleCard
        v-for="article in articlesStore.articles"
        :key="article.id"
        :article="article"
        @select="selectedArticle = $event"
      />
    </div>

    <!-- Article Detail Modal -->
    <ArticleDetailModal
      v-if="selectedArticle"
      :article="selectedArticle"
      @close="selectedArticle = null"
    />

    <!-- Pagination -->
    <div v-if="articlesStore.articles.length > 0" class="flex items-center justify-between py-6 border-t border-gray-100 mt-2">
      <p class="text-sm text-gray-400 font-medium">
        Showing {{ articlesStore.articles.length }} of {{ articlesStore.total }} articles
      </p>
      <div class="flex gap-2">
        <button
          :disabled="articlesStore.page === 1"
          @click="prevPage"
          class="px-4 py-2 border border-gray-200 rounded-lg text-sm font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-30 transition-all"
        >← Previous</button>
        <button
          :disabled="articlesStore.articles.length < articlesStore.size"
          @click="nextPage"
          class="px-4 py-2 border border-gray-200 rounded-lg text-sm font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-30 transition-all"
        >Next →</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home-page {
  padding: 28px 32px 32px;
  max-width: 1200px;
}
.page-header {
  margin-bottom: 24px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.page-title {
  font-size: 1.75rem;
  font-weight: 800;
  background: linear-gradient(90deg, #0f172a 0%, #334155 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.02em;
}
.page-sub {
  font-size: 0.85rem;
  color: #94a3b8;
  margin-top: 4px;
}

/* Upload PDF button */
.pdf-upload-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  border-radius: 9px;
  border: 1px solid #e0e7ff;
  background: #f5f3ff;
  color: #6366f1;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
  flex-shrink: 0;
}
.pdf-upload-btn:hover {
  background: #ede9fe;
  border-color: #c7d2fe;
}

/* Modal backdrop */
.pdf-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

/* Modal panel */
.pdf-modal {
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 24px 60px rgba(0,0,0,0.18);
  width: 100%;
  max-width: 620px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.pdf-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}
.pdf-modal-title {
  font-size: 1rem;
  font-weight: 800;
  color: #0f172a;
}
.pdf-modal-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 7px;
  border: none;
  background: #f1f5f9;
  color: #64748b;
  cursor: pointer;
  transition: background 0.15s;
}
.pdf-modal-close:hover { background: #e2e8f0; }

/* Drop zone */
.pdf-drop-zone {
  margin: 18px 22px 0;
  border: 2px dashed #c7d2fe;
  border-radius: 12px;
  background: #fafafe;
  padding: 28px 16px;
  text-align: center;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
  flex-shrink: 0;
}
.pdf-drop-zone:hover, .pdf-drop-zone.dragging {
  border-color: #6366f1;
  background: #eef2ff;
}
.pdf-drop-zone.has-file {
  border-color: #6ee7b7;
  background: #f0fdf4;
}
.drop-label {
  font-size: 0.88rem;
  font-weight: 600;
  color: #334155;
  margin: 0;
}
.drop-hint {
  font-size: 0.75rem;
  color: #94a3b8;
  margin: 0;
}

/* Actions row */
.pdf-modal-actions {
  display: flex;
  gap: 10px;
  padding: 14px 22px 0;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.pdf-extract-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 22px;
  border-radius: 9px;
  border: none;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.15s;
}
.pdf-extract-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.pdf-extract-btn:not(:disabled):hover { opacity: 0.87; }
.pdf-download-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 20px;
  border-radius: 9px;
  border: 1px solid #6ee7b7;
  background: #f0fdf4;
  color: #059669;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
}
.pdf-download-btn:hover { background: #dcfce7; }

/* Error */
.pdf-error-msg {
  margin: 10px 22px 0;
  padding: 9px 14px;
  border-radius: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
  font-size: 0.8rem;
  flex-shrink: 0;
}

/* Results */
.pdf-results {
  flex: 1;
  overflow-y: auto;
  padding: 14px 22px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.pdf-result-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.pdf-chip {
  padding: 3px 10px;
  border-radius: 20px;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  color: #6366f1;
  font-size: 0.73rem;
  font-weight: 700;
}
.pdf-result-title {
  font-size: 0.92rem;
  font-weight: 700;
  color: #0f172a;
  border-left: 3px solid #6366f1;
  padding-left: 10px;
}
.pdf-pages { display: flex; flex-direction: column; gap: 10px; }
.pdf-page-block {
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}
.pdf-page-label {
  padding: 5px 12px;
  font-size: 0.7rem;
  font-weight: 700;
  color: #94a3b8;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.pdf-page-text {
  padding: 12px;
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.65;
  color: #475569;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Courier New', monospace;
  max-height: 260px;
  overflow-y: auto;
  background: #fff;
}

/* Spinner */
.pdf-spin {
  width: 15px;
  height: 15px;
  animation: spin 0.9s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useArticlesStore } from '@/stores/articles'
import { useFiltersStore } from '@/stores/filters'
import ArticleCard from '@/components/ArticleCard.vue'
import FilterBar from '@/components/FilterBar.vue'
import ArticleDetailModal from '@/components/ArticleDetailModal.vue'
import api from '@/services/api.js'

const articlesStore = useArticlesStore()
const filtersStore = useFiltersStore()
const selectedArticle = ref(null)

// Local today string (IST-safe) used when store date hasn't been set yet
function _localToday() {
  const d = new Date()
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, '0'),
    String(d.getDate()).padStart(2, '0'),
  ].join('-')
}

const reloadData = () => {
  const filters = {
    date: filtersStore.selectedDate || _localToday(),
  }
  if (filtersStore.selectedEditionId)  filters.edition_id  = filtersStore.selectedEditionId
  if (filtersStore.selectedSectionId)  filters.section_id  = filtersStore.selectedSectionId
  articlesStore.fetchArticles(filters)
}

// Initial fetch
onMounted(async () => {
  if (filtersStore.sections.length === 0) {
    await filtersStore.init()
  }
  reloadData()
})

// Watch filters for changes
watch(
  [
    () => filtersStore.selectedEditionId,
    () => filtersStore.selectedSectionId,
    () => filtersStore.selectedDate
  ],
  () => {
    articlesStore.setPage(1) // Reset to page 1 on filter change
    reloadData()
  }
)

const nextPage = () => {
  articlesStore.setPage(articlesStore.page + 1)
  reloadData()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const prevPage = () => {
  if (articlesStore.page > 1) {
    articlesStore.setPage(articlesStore.page - 1)
    reloadData()
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

// ── PDF Upload ────────────────────────────────────────────────────────────────
const showPdfModal = ref(false)
const pdfFileInput = ref(null)
const pdfFile      = ref(null)
const pdfDragging  = ref(false)
const pdfLoading   = ref(false)
const pdfError     = ref('')
const pdfResult    = ref(null)

function closePdfModal() {
  showPdfModal.value = false
  pdfFile.value      = null
  pdfResult.value    = null
  pdfError.value     = ''
  if (pdfFileInput.value) pdfFileInput.value.value = ''
}

function onPdfFileChange(e) {
  const f = e.target.files[0]
  if (f) { pdfFile.value = f; pdfResult.value = null; pdfError.value = '' }
}

function onPdfDrop(e) {
  pdfDragging.value = false
  const f = e.dataTransfer.files[0]
  if (f && f.type === 'application/pdf') {
    pdfFile.value = f; pdfResult.value = null; pdfError.value = ''
  } else {
    pdfError.value = 'Please drop a valid PDF file.'
  }
}

async function extractPdf() {
  if (!pdfFile.value) return
  pdfLoading.value = true
  pdfError.value   = ''
  pdfResult.value  = null
  try {
    const { data } = await api.uploadPdf(pdfFile.value)
    pdfResult.value = data
  } catch (err) {
    pdfError.value = err?.response?.data?.detail || 'Extraction failed. Please try again.'
  } finally {
    pdfLoading.value = false
  }
}

function downloadPdfJson() {
  if (!pdfResult.value) return
  const blob = new Blob([JSON.stringify(pdfResult.value, null, 2)], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = (pdfResult.value.filename || 'extracted').replace(/\.pdf$/i, '') + '_extracted.json'
  a.click()
  URL.revokeObjectURL(url)
}
</script>
