<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
    @click.self="close"
  >
    <div class="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">

      <!-- Header -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100">
        <span class="text-xs font-bold text-brand-500 uppercase tracking-widest">
          {{ article.section?.name || 'General' }}
        </span>
        <div class="flex items-center gap-4">
          <span class="text-xs font-semibold text-gray-400">{{ todayDate }}</span>
          <button @click="close" class="text-gray-400 hover:text-gray-700 transition-colors" aria-label="Close">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- Body -->
      <div class="overflow-y-auto flex-1 px-6 py-5 space-y-4">

        <!-- Live extraction steps -->
        <div v-if="loading" class="space-y-3">
          <div
            v-for="(step, i) in steps"
            :key="i"
            class="flex items-center gap-3 text-sm"
            :class="i === steps.length - 1 ? 'text-gray-800 font-semibold' : 'text-gray-400'"
          >
            <!-- Spinner on last step, checkmark on done steps -->
            <svg v-if="i === steps.length - 1" class="animate-spin w-4 h-4 text-brand-500 shrink-0" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
            </svg>
            <svg v-else class="w-4 h-4 text-green-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/>
            </svg>
            {{ step }}
          </div>
        </div>

        <!-- Extracted content -->
        <template v-else>
          <!-- Image -->
          <img
            v-if="imageUrl"
            :src="imageUrl"
            :alt="article.title"
            class="w-full rounded-xl object-cover max-h-64"
            @error="imageUrl = null"
          />

          <!-- Title -->
          <h2 class="text-2xl font-bold text-gray-900 leading-tight">{{ article.title }}</h2>
          <p v-if="article.subtitle" class="text-sm font-semibold text-gray-500 -mt-2">{{ article.subtitle }}</p>

          <!-- Meta -->
          <div class="flex flex-wrap gap-2 text-[11px] font-medium text-gray-500">
            <span v-if="article.byline">By {{ article.byline }}</span>
            <span v-if="article.page_label" class="bg-gray-100 px-2 py-0.5 rounded">{{ article.page_label }}</span>
            <span v-if="article.location" class="bg-gray-100 px-2 py-0.5 rounded">📍 {{ article.location }}</span>
          </div>

          <!-- Content -->
          <div class="text-sm text-gray-700 leading-relaxed whitespace-pre-line">{{ displayContent }}</div>

          <!-- Fallback note -->
          <p v-if="usedFallback" class="text-[11px] text-gray-400 italic border-t border-gray-100 pt-3">
            Full content requires epaper login session. Showing article summary.
          </p>

          <!-- Tags -->
          <div v-if="article.tags?.length" class="flex flex-wrap gap-1 pt-2 border-t border-gray-100">
            <span v-for="tag in article.tags" :key="tag.id" class="text-[10px] font-bold text-brand-400">
              #{{ tag.name }}
            </span>
          </div>
        </template>
      </div>

      <!-- Footer -->
      <div class="px-6 py-4 border-t border-gray-100 flex items-center justify-between bg-gray-50">
        <span class="text-[11px] text-gray-400 font-medium italic">Today: {{ todayDate }}</span>
        <a
          :href="article.url"
          target="_blank"
          class="flex items-center gap-1 text-xs font-bold text-brand-500 hover:text-brand-700 transition-colors"
        >
          Open Original
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M14 5l7 7m0 0l-7 7m7-7H3"/>
          </svg>
        </a>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api from '@/services/api'

const props = defineProps({
  article: { type: Object, required: true }
})
const emit = defineEmits(['close'])

const loading = ref(true)
const steps = ref([])
const scrapedContent = ref('')
const imageUrl = ref(null)
const todayDate = ref('')

let es = null

const usedFallback = computed(() => !scrapedContent.value && !!props.article.summary)
const displayContent = computed(() => scrapedContent.value || props.article.summary || 'No content available.')

function close() {
  if (es) { es.close(); es = null }
  emit('close')
}

onMounted(() => {
  todayDate.value = new Intl.DateTimeFormat('en-IN', {
    day: 'numeric', month: 'long', year: 'numeric'
  }).format(new Date())

  es = new EventSource(api.articleContentStreamUrl(props.article.url))

  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)

      if (data.type === 'step') {
        steps.value.push(data.message)
      } else if (data.type === 'done') {
        steps.value.push('Done!')
        scrapedContent.value = data.content || ''
        imageUrl.value = data.image_url || null
        if (data.date) todayDate.value = data.date
        es.close()
        es = null
        loading.value = false
      }
    } catch {
      // ignore parse errors
    }
  }

  es.onerror = () => {
    if (es) { es.close(); es = null }
    loading.value = false
  }
})

onUnmounted(() => {
  if (es) { es.close(); es = null }
})
</script>
