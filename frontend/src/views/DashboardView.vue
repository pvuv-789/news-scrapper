<template>
  <div class="dashboard">
    <!-- Header -->
    <div class="dash-header">
      <h1 class="dash-title">Viewer Dashboard</h1>
      <p class="dash-sub">Quick access to the Newspaper Viewer, Classifieds Viewer, and Tenders Viewer</p>
    </div>

    <!-- Tab switcher -->
    <div class="tab-bar">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'newspaper' }"
        @click="activeTab = 'newspaper'"
      >
        <svg class="tab-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10l4 4v12a2 2 0 01-2 2z" />
        </svg>
        Newspaper Viewer
        <a :href="viewerUrl" target="_blank" rel="noopener" class="open-btn" @click.stop title="Open in new tab">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:13px;height:13px">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </button>

      <button
        class="tab-btn"
        :class="{ active: activeTab === 'classifieds' }"
        @click="activeTab = 'classifieds'"
      >
        <svg class="tab-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M4 6h16M4 10h16M4 14h10M4 18h6" />
        </svg>
        Classifieds Viewer
        <a :href="classifiedsUrl" target="_blank" rel="noopener" class="open-btn" @click.stop title="Open in new tab">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:13px;height:13px">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </button>

      <button
        class="tab-btn"
        :class="{ active: activeTab === 'tenders' }"
        @click="activeTab = 'tenders'"
      >
        <svg class="tab-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        Tenders Viewer
        <a :href="tendersUrl" target="_blank" rel="noopener" class="open-btn" @click.stop title="Open in new tab">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:13px;height:13px">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </button>
    </div>

    <!-- Iframe panels -->
    <div class="iframe-wrap">
      <template v-if="backendConfigured">
        <iframe
          v-show="activeTab === 'newspaper'"
          :src="viewerUrl"
          class="viewer-frame"
          title="Newspaper Viewer"
          allow="fullscreen"
        />
        <iframe
          v-show="activeTab === 'classifieds'"
          :src="classifiedsUrl"
          class="viewer-frame"
          title="Classifieds Viewer"
          allow="fullscreen"
        />
        <iframe
          v-show="activeTab === 'tenders'"
          :src="tendersUrl"
          class="viewer-frame"
          title="Tenders Viewer"
          allow="fullscreen"
        />
      </template>
      <div v-else class="no-backend">
        <div class="no-backend-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:48px;height:48px">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
              d="M5 12H3m18 0h-2M12 5V3m0 18v-2M7.05 7.05 5.636 5.636m12.728 12.728L16.95 16.95M7.05 16.95l-1.414 1.414M18.364 5.636 16.95 7.05M12 8a4 4 0 100 8 4 4 0 000-8z" />
          </svg>
        </div>
        <h2 class="no-backend-title">Backend Not Connected</h2>
        <p class="no-backend-desc">
          The <strong>{{ activeTabLabel }}</strong> requires a running backend server.<br>
          Set <code>VITE_API_BASE_URL</code> in your Vercel environment variables to connect.
        </p>
        <div class="no-backend-steps">
          <div class="step">
            <span class="step-num">1</span>
            <span>Deploy your backend (FastAPI) to a public URL</span>
          </div>
          <div class="step">
            <span class="step-num">2</span>
            <span>In Vercel → Settings → Environment Variables</span>
          </div>
          <div class="step">
            <span class="step-num">3</span>
            <span>Add <code>VITE_API_BASE_URL</code> = <code>https://your-backend-url/api</code></span>
          </div>
          <div class="step">
            <span class="step-num">4</span>
            <span>Redeploy the frontend</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const backendConfigured = !!import.meta.env.VITE_API_BASE_URL

const BASE = import.meta.env.VITE_API_BASE_URL
  ? import.meta.env.VITE_API_BASE_URL.replace('/api', '')
  : ''

const viewerUrl      = `${BASE}/viewer`
const classifiedsUrl = `${BASE}/viewer/classifieds`
const tendersUrl     = `${BASE}/viewer/tenders`

const activeTab = ref('newspaper')

const activeTabLabel = computed(() => {
  if (activeTab.value === 'newspaper')  return 'Newspaper Viewer'
  if (activeTab.value === 'classifieds') return 'Classifieds Viewer'
  return 'Tenders Viewer'
})
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 40%, #0f172a 100%);
}

.dash-header {
  padding: 18px 28px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  background: rgba(15,23,42,0.7);
  backdrop-filter: blur(8px);
}
.dash-title {
  font-size: 1.2rem;
  font-weight: 800;
  background: linear-gradient(90deg, #f87171, #fb923c, #facc15);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.02em;
}
.dash-sub {
  font-size: 0.75rem;
  color: #475569;
  margin-top: 3px;
}

.tab-bar {
  display: flex;
  gap: 8px;
  padding: 12px 28px;
  background: rgba(15,23,42,0.5);
  border-bottom: 1px solid rgba(255,255,255,0.06);
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  border-radius: 9px;
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.04);
  color: #64748b;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.tab-btn:hover {
  background: rgba(255,255,255,0.08);
  color: #94a3b8;
}
.tab-btn.active {
  background: linear-gradient(135deg, rgba(99,102,241,0.25), rgba(139,92,246,0.15));
  border-color: rgba(139,92,246,0.4);
  color: #a78bfa;
}

.tab-icon {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
}

.open-btn {
  display: inline-flex;
  align-items: center;
  margin-left: 4px;
  color: inherit;
  opacity: 0.5;
  text-decoration: none;
  transition: opacity 0.15s;
}
.open-btn:hover { opacity: 1; }

.iframe-wrap {
  flex: 1;
  overflow: hidden;
  background: #0f172a;
}
.viewer-frame {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}
</style>
