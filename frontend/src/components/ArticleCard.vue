<template>
  <div class="glass-card rounded-2xl overflow-hidden hover:shadow-2xl transition-all duration-300 group flex flex-col h-full bg-white relative">
    <!-- Duplicate Indicator -->
    <div v-if="article.is_duplicate" class="absolute top-0 right-0 bg-yellow-400 text-yellow-900 text-[10px] font-bold px-3 py-1 rounded-bl-xl z-10 uppercase tracking-tighter">
      Regional Variation
    </div>

    <!-- Article Info -->
    <div class="p-5 flex-grow flex flex-col">
      <!-- Section & Date -->
      <div class="flex items-center justify-between mb-3">
        <span class="text-[11px] font-bold text-brand-500 uppercase tracking-widest">
          {{ article.section?.name || 'General' }}
        </span>
        <span class="text-[10px] font-medium text-gray-400">
          {{ formattedDate }}
        </span>
      </div>

      <!-- Title / Subtitle -->
      <h3 class="text-xl font-bold text-gray-900 mb-2 leading-tight group-hover:text-brand-600 transition-colors">
        {{ article.title }}
      </h3>
      <p v-if="article.subtitle" class="text-sm font-semibold text-gray-500 mb-3 leading-snug">
        {{ article.subtitle }}
      </p>

      <!-- Meta (Page / Loc) -->
      <div class="flex flex-wrap gap-2 mb-4">
        <span v-if="article.page_label" class="bg-gray-100 text-gray-600 text-[10px] font-bold px-2 py-1 rounded">
          {{ article.page_label }}
        </span>
        <span v-if="article.location" class="bg-gray-100 text-gray-600 text-[10px] font-bold px-2 py-1 rounded">
          📍 {{ article.location }}
        </span>
        <span v-if="article.byline" class="text-[10px] font-medium text-gray-400 self-center">
          By {{ article.byline }}
        </span>
      </div>

      <!-- Summary -->
      <p class="text-sm text-gray-600 line-clamp-4 leading-relaxed mb-6">
        {{ article.summary || 'Summary unavailable for this article.' }}
      </p>

      <!-- Tags -->
      <div v-if="article.tags?.length" class="flex flex-wrap gap-1 mb-6">
        <span v-for="tag in article.tags" :key="tag.id" class="text-[10px] font-bold text-brand-400 hover:text-brand-600">
          #{{ tag.name }}
        </span>
      </div>

      <!-- CTA -->
      <div class="mt-auto pt-4 border-t border-gray-50 flex items-center justify-between">
        <span class="text-[10px] font-medium text-gray-400 italic">
          {{ article.word_count_estimate }} words est.
        </span>
        <a 
          :href="article.url" 
          target="_blank" 
          class="flex items-center text-xs font-bold text-brand-500 hover:text-brand-700 transition-colors gap-1 group-hover:gap-2"
        >
          Read Full Story
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M14 5l7 7m0 0l-7 7m7-7H3" />
          </svg>
        </a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  article: {
    type: Object,
    required: true
  }
})

const formattedDate = computed(() => {
  if (!props.article.published_at) return ''
  const date = new Date(props.article.published_at)
  return new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short'
  }).format(date)
})
</script>
