import axios from 'axios'

// Static map: city_code (from DB seed) → numeric EID used by Daily Thanthi epaper API
const CITY_CODE_TO_EID = {
  'andhra':                   '247',
  'bengaluru':                '137',
  'chengalpattu':             '264',
  'chennai':                  '77',
  'chidambaram-virudhachalam':'254',
  'coimbatore':               '226',
  'colombo':                  '263',
  'cuddalore':                '262',
  'dharampuri':               '261',
  'dindigul':                 '261',
  'dindigul-district':        '212',
  'dubai':                    '186',
  'erode':                    '234',
  'erode-district':           '231',
  'hosur':                    'hos',
  'kallakurichi':             '251',
  'kancheepuram':             '192',
  'kangeyam-dharapuram':      '227',
  'karur':                    '270',
  'kerala-theni':             '211',
  'kerala-coimbatore':        '233',
  'kerala-nagarcoil':         '243',
  'krishnagiri':              '235',
  'kumbakonam-pattukottai':   '221',
  'kunnatur':                 '259',
  'madurai':                  '210',
  'mangalore-raichur':        '195',
  'mumbai':                   '147',
  'mysore-kgf':               '196',
  'nagai-karaikal':           '219',
  'nagarcoil':                '246',
  'nagarcoil-district':       '244',
  'namakkal':                 '236',
  'nilgiris':                 '224',
  'perambalur-ariyalur':      '215',
  'pollachi-mettupalayam':    '225',
  'pondicherry':              '157',
  'pudukkottai':              '216',
  'ramnad-sivagangai':        '207',
  'ranipet-tirupathur':       '249',
  'salem':                    '238',
  'salem-district':           '256',
  'tanjore':                  '222',
  'thoothukudi':              '239',
  'tirunelveli':              '240',
  'tirunelveli-district':     '255',
  'tirupur':                  '230',
  'tirupur-district':         '257',
  'tiruvallur':               '255',
  'tiruvannamalai':           '248',
  'tiruvarur':                '220',
  'trichy':                   '218',
  'vellore':                  '250',
  'villupuram':               '252',
  'villupuram-cuddalore':     '252',
  'virudhunagar':             '208',
}

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
    },

    // Full article content + image extraction (SSE stream URL)
    articleContentStreamUrl(url) {
        const base = import.meta.env.VITE_API_BASE_URL || '/api'
        return `${base}/scrape/article-content-stream?url=${encodeURIComponent(url)}`
    },

    // Download today's edition PDF (returns arraybuffer)
    downloadEditionPdf(cityCode, date) {
        const params = new URLSearchParams({ edition: cityCode })
        if (date) params.set('date', date)
        return apiClient.get(`/scrape/edition-daily-pdf?${params}`, { responseType: 'arraybuffer' })
    },

    // Classified Images — fetch ad images for a given pgid
    getClassifiedsImages(pgid) {
        return apiClient.get(`/scrape/classifieds-images?pgid=${encodeURIComponent(pgid)}`)
    },

    // URL for the standalone classifieds viewer page (served at /viewer/classifieds)
    // Pass pgid directly, or let the viewer show the input form if pgid is unknown.
    classifiedsViewerUrl(pgid = '', edition = '', date = '', eid = '') {
        const base = import.meta.env.VITE_API_BASE_URL
            ? import.meta.env.VITE_API_BASE_URL.replace('/api', '')
            : ''
        const params = new URLSearchParams()
        if (pgid)    params.set('pgid',    pgid)
        if (edition) params.set('edition', edition)
        if (date)    params.set('date',    date)
        if (eid)     params.set('eid',     eid)
        return `${base}/viewer/classifieds?${params}`
    }
}
