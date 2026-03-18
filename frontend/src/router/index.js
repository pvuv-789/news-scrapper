import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import EpaperView from '@/views/EpaperView.vue'
import DashboardView from '@/views/DashboardView.vue'

const router = createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes: [
        {
            path: '/',
            name: 'home',
            component: HomeView
        },
        {
            path: '/edition/:id',
            name: 'edition',
            component: HomeView
        },
        {
            path: '/epaper',
            name: 'epaper',
            component: EpaperView
        },
        {
            path: '/dashboard',
            name: 'dashboard',
            component: DashboardView
        },
        {
            path: '/:pathMatch(.*)*',
            redirect: '/'
        }
    ],
    scrollBehavior() {
        return { top: 0 }
    }
})

export default router
