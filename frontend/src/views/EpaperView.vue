<template>
  <div class="epaper-page">
    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>E-Paper Viewer ஏற்றுகிறது...</p>
    </div>
    <div v-if="error" class="error-state">
      <p>{{ error }}</p>
      <p class="hint">
        Backend இயங்குகிறதா என்று சரிபாருங்கள்:<br/>
        <code>cd backend &amp;&amp; uvicorn main:app --reload</code><br/>
        பிறகு <code>gen_html.py</code> இயக்கி <code>thanthi_layout.html</code> உருவாக்குங்கள்.
      </p>
    </div>
    <iframe
      v-show="!loading && !error"
      ref="iframeEl"
      src="/viewer"
      title="Daily Thanthi E-Paper Viewer"
      class="viewer-frame"
      @load="onLoad"
      @error="onError"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'

const iframeEl = ref(null)
const loading  = ref(true)
const error    = ref('')

function onLoad() {
  loading.value = false
  // If the iframe landed on an error page (e.g. 404), the content will say so.
  try {
    const doc = iframeEl.value?.contentDocument
    if (doc && doc.title && doc.title.toLowerCase().includes('not found')) {
      error.value = 'Viewer not found (404). Run gen_html.py first.'
    }
  } catch (_) {
    // cross-origin — can't read content; assume it's fine
  }
}

function onError() {
  loading.value = false
  error.value = 'Viewer ஏற்ற முடியவில்லை. Backend இயங்குகிறதா என்று சரிபாருங்கள்.'
}
</script>

<style scoped>
.epaper-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #e8e8e8;
}

.viewer-frame {
  flex: 1;
  width: 100%;
  border: none;
}

.loading-state,
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  gap: 16px;
  color: #555;
  font-size: 14px;
  text-align: center;
}

.error-state {
  color: #900;
}

.error-state .hint {
  color: #555;
  margin-top: 8px;
  line-height: 1.8;
}

.error-state code {
  background: #f4f4f4;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
  color: #333;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #eee;
  border-top-color: #c00;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
