<template>
  <div class="min-h-screen flex flex-col">
    <NavBar />
    <main class="flex-grow container mx-auto px-4 py-8">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
    <footer class="bg-white border-t border-gray-200 py-6 mt-12">
      <div class="container mx-auto px-4 text-center text-gray-500 text-sm">
        <p>&copy; 2026 E-Paper News Aggregator. Data source: Daily Thanthi.</p>
        <p class="mt-1">Metadata and summaries provided under Fair Use.</p>
      </div>
    </footer>
  </div>
</template>

<script setup>
import NavBar from '@/components/NavBar.vue'
</script>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
