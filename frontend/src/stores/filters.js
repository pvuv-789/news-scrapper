import { defineStore } from 'pinia'
import api from '@/services/api'

export const useFiltersStore = defineStore('filters', {
    state: () => ({
        editions: [],
        sections: [],
        selectedEditionId: null,
        selectedSectionId: null,
        selectedDate: null,
        loading: false
    }),

    actions: {
        async init() {
            this.loading = true
            try {
                const [editionsRes, sectionsRes] = await Promise.all([
                    api.getEditions(),
                    api.getSections()
                ])
                this.editions = editionsRes.data
                this.sections = sectionsRes.data

                // Set default edition if none selected
                if (!this.selectedEditionId && this.editions.length > 0) {
                    this.selectedEditionId = this.editions[0].id
                }
            } catch (err) {
                console.error('Failed to initialize filters:', err)
            } finally {
                this.loading = false
            }
        },

        setEdition(id) {
            this.selectedEditionId = id
        },

        setSection(id) {
            this.selectedSectionId = id
        },

        setDate(date) {
            this.selectedDate = date
        }
    },

    getters: {
        currentEditionName: (state) => {
            const edition = state.editions.find(e => e.id === state.selectedEditionId)
            return edition ? edition.display_name : 'All Editions'
        }
    }
})
