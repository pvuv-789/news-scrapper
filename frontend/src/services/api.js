import axios from 'axios'

const apiClient = axios.create({
    baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
    headers: {
        'Content-Type': 'application/json'
    }
})

export default {
    // Articles
    getArticles(params) {
        return apiClient.get('/articles', { params })
    },
    getArticle(id) {
        return apiClient.get(`/articles/${id}`)
    },

    // Editions
    getEditions() {
        return apiClient.get('/editions')
    },

    // Sections
    getSections() {
        return apiClient.get('/sections')
    },

    // Tags
    getTags() {
        return apiClient.get('/tags')
    },
    getArticlesByTag(tagSlug, params) {
        return apiClient.get(`/tags/${tagSlug}/articles`, { params })
    },

    // PDF Scraper
    scrapePdf(url) {
        return apiClient.post('/scrape/pdf', { url })
    },

    // Webpage → PDF (returns binary PDF for download)
    scrapeWebpagePdf(url) {
        return apiClient.post('/scrape/webpage-pdf', { url }, { responseType: 'arraybuffer' })
    },

    // URL → PDF: scrape any public webpage and download as PDF
    scrapeUrlToPdf(url) {
        return apiClient.post('/scrape/url-to-pdf', { url }, { responseType: 'arraybuffer' })
    },

    // Screenshot: render page and return PNG
    scrapeScreenshot(url) {
        return apiClient.post('/scrape/webpage-screenshot', { url }, { responseType: 'arraybuffer' })
    },

    // JSON: scrape and return structured article data
    scrapeJson(url) {
        return apiClient.post('/scrape/webpage-json', { url })
    }
}
