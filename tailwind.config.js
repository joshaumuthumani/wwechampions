/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#09090a',
          900: '#111113',
          850: '#18181b',
          800: '#202024',
          700: '#2d2d32',
        },
        gold: {
          300: '#f8d77a',
          500: '#d8a72f',
        },
      },
      boxShadow: {
        card: '0 18px 60px rgba(0, 0, 0, 0.26)',
      },
    },
  },
  plugins: [],
};
