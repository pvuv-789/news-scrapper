<template>
  <div class="bg-white border-b border-gray-100 py-4 mb-8">
    <div class="flex flex-wrap items-center gap-4">
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

      <!-- Search / Loading Spacer -->
      <div class="flex-grow flex justify-end items-end h-full">
        <div v-if="articlesStore.loading" class="flex items-center space-x-2 text-brand-500 mb-2">
          <svg class="animate-spin h-5 w-5" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <span class="text-xs font-bold uppercase tracking-widest">Refreshing</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useFiltersStore } from '@/stores/filters'
import { useArticlesStore } from '@/stores/articles'

const filtersStore = useFiltersStore()
const articlesStore = useArticlesStore()

const selectedDate = ref(new Date().toISOString().substr(0, 10))

// Sync local date to store
watch(selectedDate, (newVal) => {
  filtersStore.setDate(newVal)
}, { immediate: true })
</script>
