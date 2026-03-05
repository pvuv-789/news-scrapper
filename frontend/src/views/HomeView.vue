<template>
  <div class="space-y-6">
    <!-- Header Area -->
    <div class="flex flex-col md:flex-row md:items-end justify-between gap-4">
      <div>
        <h1 class="text-3xl font-bold text-gray-900 tracking-tight">
          {{ filtersStore.currentEditionName }} News
        </h1>
        <p class="text-gray-500 mt-1 font-medium">
          Top stories curated from the Daily Thanthi E-Paper.
        </p>
      </div>
    </div>

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
      />
    </div>

    <!-- Pagination (Simplified) -->
    <div v-if="articlesStore.articles.length > 0" class="flex items-center justify-between py-8 border-t border-gray-100">
      <p class="text-sm text-gray-500 font-medium">
        Showing {{ articlesStore.articles.length }} of {{ articlesStore.total }} articles
      </p>
      <div class="flex space-x-2">
        <button 
          :disabled="articlesStore.page === 1"
          @click="prevPage"
          class="px-4 py-2 border border-gray-200 rounded-lg text-sm font-bold text-gray-600 hover:bg-gray-50 disabled:opacity-30 disabled:hover:bg-transparent transition-all"
        >
          Previous
        </button>
        <button 
          :disabled="articlesStore.articles.length < articlesStore.size"
          @click="nextPage"
          class="px-4 py-2 border border-gray-200 rounded-lg text-sm font-bold text-gray-600 hover:bg-gray-50 disabled:opacity-30 disabled:hover:bg-transparent transition-all"
        >
          Next
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, watch } from 'vue'
import { useArticlesStore } from '@/stores/articles'
import { useFiltersStore } from '@/stores/filters'
import ArticleCard from '@/components/ArticleCard.vue'
import FilterBar from '@/components/FilterBar.vue'

const articlesStore = useArticlesStore()
const filtersStore = useFiltersStore()

const reloadData = () => {
  articlesStore.fetchArticles({
    edition_id: filtersStore.selectedEditionId,
    section_id: filtersStore.selectedSectionId,
    date: filtersStore.selectedDate
  })
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
</script>
