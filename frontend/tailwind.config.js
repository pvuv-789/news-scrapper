/** @type {import('tailwindcss').Config} */
export default {
    content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
    theme: {
        extend: {
            colors: {
                brand: {
                    50: '#fdf4f4',
                    100: '#fbe8e8',
                    200: '#f6c4c4',
                    300: '#ee9393',
                    400: '#e35757',
                    500: '#d42b2b',   // Primary — Daily Thanthi red
                    600: '#b81e1e',
                    700: '#951818',
                    800: '#7b1818',
                    900: '#661919',
                }
            },
            fontFamily: {
                sans: ['Inter', 'system-ui', 'sans-serif'],
            }
        }
    },
    plugins: []
}
