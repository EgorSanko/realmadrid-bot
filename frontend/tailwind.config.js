/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './public/**/*.html',
    './src/**/*.{js,jsx,ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        rm: {
          gold: '#FEBE10',
          purple: '#412881',
        },
      },
    },
  },
  plugins: [],
};
