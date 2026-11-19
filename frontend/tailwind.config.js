/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#12121a',
          raised: '#1a1a24',
          overlay: '#22222e'
        },
        accent: {
          DEFAULT: '#7c3aed',
          glow: '#9333ea',
          muted: '#6d28d9'
        }
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif']
      },
      boxShadow: {
        glow: '0 0 24px rgba(124, 58, 237, 0.35)',
        card: '0 4px 24px rgba(0, 0, 0, 0.45)'
      }
    }
  },
  plugins: []
};
