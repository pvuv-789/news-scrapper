import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ArticleCard from '@/components/ArticleCard.vue'

describe('ArticleCard.vue', () => {
    const article = {
        id: '1',
        title: 'Test Article',
        subtitle: 'Test Subtitle',
        summary: 'Test Summary',
        url: 'https://example.com',
        published_at: '2026-02-25T12:00:00Z',
        section: { name: 'Politics' },
        is_duplicate: false,
        tags: [{ id: '1', name: 'TestTag' }]
    }

    it('renders article title and summary', () => {
        const wrapper = mount(ArticleCard, {
            props: { article }
        })

        expect(wrapper.text()).toContain('Test Article')
        expect(wrapper.text()).toContain('Test Summary')
    })

    it('shows regional variation badge when is_duplicate is true', async () => {
        const duplicateArticle = { ...article, is_duplicate: true }
        const wrapper = mount(ArticleCard, {
            props: { article: duplicateArticle }
        })

        expect(wrapper.text()).toContain('Regional Variation')
    })
})
