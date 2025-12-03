/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'n8n-green': '#00C16E',
        'n8n-orange': '#FF6D5A',
        'n8n-blue': '#0066FF',
        'n8n-purple': '#7B61FF',
        'n8n-dark': '#1A1A2E',
        'n8n-gray': '#2D2D3F',
      },
    },
  },
  plugins: [],
}
