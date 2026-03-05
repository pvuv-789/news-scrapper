import { defineStore } from 'pinia'
import api from '@/services/api'

export const useArticlesStore = defineStore('articles', {
    state: () => ({
        articles: [],
        total: 0,
        page: 1,
        size: 20,
        loading: false,
        error: null
    }),

    actions: {
        async fetchArticles(filters = {}) {
            this.loading = true
            this.error = null
            try {
                const response = await api.getArticles({
                    page: this.page,
                    size: this.size,
                    ...filters
                })
                this.articles = response.data.items
                this.total = response.data.total
            } catch (err) {
                this.error = 'Failed to load articles. Please try again later.'
                console.error(err)
            } finally {
                this.loading = false
            }
        },

        setPage(page) {
            this.page = page
        }
    }
})
