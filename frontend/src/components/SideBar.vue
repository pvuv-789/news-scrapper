<template>
  <aside class="sidebar">
    <!-- Logo -->
    <div class="sidebar-logo">
      <div class="logo-icon">DT</div>
      <div class="logo-text">
        <span class="logo-gradient">E-Scrapper</span>
        <span class="logo-version">v2.0</span>
      </div>
    </div>

    <!-- Date badge -->
    <div class="sidebar-date">
      <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
      </svg>
      {{ today }}
    </div>

    <div class="sidebar-divider"/>

    <!-- Navigation -->
    <div class="nav-section-label">Navigation</div>
    <nav class="sidebar-nav">
      <router-link to="/" class="nav-item" :class="{ active: $route.name === 'home' || $route.name === 'edition' }">
        <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/>
        </svg>
        <span>News Feed</span>
      </router-link>

      <router-link to="/dashboard" class="nav-item" :class="{ active: $route.name === 'dashboard' }">
        <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2"/>
        </svg>
        <span>Dashboard</span>
      </router-link>
    </nav>

    <div class="sidebar-divider"/>

    <!-- Scrape All Editions -->
    <div class="nav-section-label">Tools</div>
    <div class="sidebar-tools">
      <button class="scrape-btn" @click="openViewer">
        <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
        </svg>
        <span>Scrape All Editions</span>
      </button>
    </div>

    <!-- Footer -->
    <div class="sidebar-footer">
      <div class="footer-dot"></div>
      <span>E-Paper News Aggregator</span>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'

const today = computed(() =>
  new Intl.DateTimeFormat('en-IN', {
    weekday: 'short', day: 'numeric', month: 'short', year: 'numeric'
  }).format(new Date())
)

function openViewer() {
  const base = import.meta.env.VITE_API_BASE_URL
    ? import.meta.env.VITE_API_BASE_URL.replace('/api', '')
    : window.location.origin
  window.open(base + '/viewer', '_blank')
}
</script>

<style scoped>
.sidebar {
  width: 224px;
  min-width: 224px;
  height: 100vh;
  background: linear-gradient(180deg, #0f172a 0%, #111827 60%, #0f172a 100%);
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255,255,255,0.05);
  position: sticky;
  top: 0;
  overflow-y: auto;
}

/* ── Logo ── */
.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 22px 18px 12px;
}
.logo-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: linear-gradient(135deg, #d42b2b 0%, #ff6b6b 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 900;
  font-size: 0.9rem;
  color: #fff;
  flex-shrink: 0;
  box-shadow: 0 4px 14px rgba(212,43,43,0.45);
  letter-spacing: -0.5px;
}
.logo-text { display: flex; flex-direction: column; line-height: 1.1; }
.logo-gradient {
  font-size: 1.1rem;
  font-weight: 800;
  background: linear-gradient(90deg, #f87171 0%, #fb923c 50%, #facc15 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.3px;
}
.logo-version {
  font-size: 0.6rem;
  color: #334155;
  font-weight: 600;
  letter-spacing: 0.1em;
}

/* ── Date ── */
.sidebar-date {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 18px 14px;
  font-size: 0.7rem;
  color: #475569;
  font-weight: 500;
}

/* ── Divider ── */
.sidebar-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent);
  margin: 0 14px 10px;
}

/* ── Section label ── */
.nav-section-label {
  font-size: 0.6rem;
  font-weight: 700;
  color: #334155;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  padding: 0 18px 6px;
}

/* ── Nav ── */
.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 8px 12px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 9px;
  font-size: 0.84rem;
  font-weight: 500;
  color: #64748b;
  text-decoration: none;
  transition: all 0.15s;
  position: relative;
}
.nav-item:hover {
  background: rgba(255,255,255,0.05);
  color: #cbd5e1;
}
.nav-item.active {
  background: linear-gradient(135deg, rgba(212,43,43,0.18), rgba(239,68,68,0.08));
  color: #fca5a5;
  font-weight: 600;
}
.nav-item.active::before {
  content: '';
  position: absolute;
  left: 0; top: 6px; bottom: 6px;
  width: 3px;
  border-radius: 2px;
  background: linear-gradient(180deg, #f87171, #d42b2b);
}
.nav-icon {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
}

/* ── Tools ── */
.sidebar-tools {
  padding: 0 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.scrape-btn {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 12px;
  border-radius: 9px;
  border: none;
  cursor: pointer;
  font-size: 0.83rem;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  transition: all 0.2s;
  box-shadow: 0 2px 10px rgba(99,102,241,0.3);
  text-align: left;
}
.scrape-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(99,102,241,0.45);
}

/* ── Footer ── */
.sidebar-footer {
  margin-top: auto;
  padding: 14px 18px;
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 0.62rem;
  color: #1e293b;
}
.footer-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 6px rgba(34,197,94,0.6);
  flex-shrink: 0;
}
</style>
