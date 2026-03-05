<template>
  <header class="bg-white border-b border-gray-200 sticky top-0 z-50">
    <div class="container mx-auto px-4">
      <div class="flex items-center justify-between h-16">
        <!-- Logo -->
        <router-link to="/" class="flex items-center space-x-2">
          <div class="w-10 h-10 bg-brand-500 rounded-lg flex items-center justify-center text-white font-bold text-xl shadow-inner">
            DT
          </div>
          <span class="font-bold text-xl tracking-tight text-gray-900 hidden sm:block">
            E-Scrapper
          </span>
        </router-link>

        <!-- Navigation Tabs -->
        <nav class="hidden md:flex space-x-1 overflow-x-auto no-scrollbar max-w-2xl px-4">
          <button
            @click="filtersStore.setSection(null)"
            class="px-4 py-2 rounded-full text-sm font-medium transition-colors"
            :class="!filtersStore.selectedSectionId ? 'bg-brand-50 text-brand-600' : 'text-gray-500 hover:bg-gray-100 hover:text-gray-900'"
          >
            All
          </button>
          <button
            v-for="section in filtersStore.sections"
            :key="section.id"
            @click="filtersStore.setSection(section.id)"
            class="px-4 py-2 rounded-full text-sm font-medium transition-colors whitespace-nowrap"
            :class="filtersStore.selectedSectionId === section.id ? 'bg-brand-50 text-brand-600' : 'text-gray-500 hover:bg-gray-100 hover:text-gray-900'"
          >
            {{ section.name }}
          </button>
        </nav>

        <!-- Actions / Mobile Menu -->
        <div class="flex items-center space-x-3">
          <div class="text-xs text-gray-400 font-medium hidden lg:block">
            {{ today }}
          </div>
          <router-link
            to="/epaper"
            class="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors"
            :class="$route.name === 'epaper'
              ? 'bg-red-50 text-red-700'
              : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10l4 4v12a2 2 0 01-2 2z" />
            </svg>
            E-Paper
          </router-link>
          <PdfScrapeModal />
          <button class="p-2 text-gray-500 hover:bg-gray-100 rounded-lg md:hidden">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16m-7 6h7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
    
    <!-- Mobile Section Nav (Scrollable) -->
    <div class="md:hidden border-t border-gray-100 px-4 py-2 flex space-x-2 overflow-x-auto no-scrollbar">
       <router-link
            to="/epaper"
            class="px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap"
            :class="$route.name === 'epaper' ? 'bg-red-600 text-white' : 'bg-gray-100 text-gray-600'"
          >
            E-Paper
          </router-link>
       <button
            @click="filtersStore.setSection(null)"
            class="px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap"
            :class="!filtersStore.selectedSectionId ? 'bg-brand-500 text-white' : 'bg-gray-100 text-gray-600'"
          >
            All
          </button>
          <button
            v-for="section in filtersStore.sections"
            :key="section.id"
            @click="filtersStore.setSection(section.id)"
            class="px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap"
            :class="filtersStore.selectedSectionId === section.id ? 'bg-brand-500 text-white' : 'bg-gray-100 text-gray-600'"
          >
            {{ section.name }}
          </button>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useFiltersStore } from '@/stores/filters'
import PdfScrapeModal from '@/components/PdfScrapeModal.vue'

const filtersStore = useFiltersStore()

const today = computed(() => {
  return new Intl.DateTimeFormat('en-IN', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric'
  }).format(new Date())
})
</script>

<style scoped>
.no-scrollbar::-webkit-scrollbar {
  display: none;
}
.no-scrollbar {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
</style>
