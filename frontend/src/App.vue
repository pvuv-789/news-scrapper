<template>
  <div class="app-shell">
    <SideBar />
    <div class="content-area" :class="{ 'full-height': isFullHeightRoute }">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
      <footer v-if="!isFullHeightRoute" class="app-footer">
        <p>&copy; 2026 E-Paper News Aggregator. Data source: Daily Thanthi.</p>
        <p>Metadata and summaries provided under Fair Use.</p>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import SideBar from '@/components/SideBar.vue'

const route = useRoute()
const isFullHeightRoute = computed(() =>
  ['epaper', 'dashboard'].includes(route.name)
)
</script>

<style>
*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  font-family: 'Inter', system-ui, sans-serif;
  background: #f1f5f9;
  color: #0f172a;
}

.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.content-area {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  background: linear-gradient(160deg, #f1f5f9 0%, #e9eef6 50%, #f0f4fb 100%);
}

.content-area.full-height {
  overflow: hidden;
}

.app-footer {
  margin-top: auto;
  background: rgba(255,255,255,0.7);
  backdrop-filter: blur(8px);
  border-top: 1px solid rgba(226,232,240,0.8);
  padding: 16px 32px;
  font-size: 0.75rem;
  color: #94a3b8;
  text-align: center;
  line-height: 1.8;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
