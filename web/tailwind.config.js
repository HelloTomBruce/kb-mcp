import { heroui } from '@heroui/react';

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
    './node_modules/@heroui/theme/dist/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        grok: {
          bg: '#000000',
          sidebar: '#08080a',
          surface: '#0d0d10',
          card: '#121216',
          cardHover: '#18181f',
          border: 'rgba(255, 255, 255, 0.08)',
          borderHover: 'rgba(255, 255, 255, 0.16)',
          text: '#f4f4f6',
          muted: '#8e8e98',
          subtle: '#52525c',
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Geist', 'Inter', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'SF Mono', 'Fira Code', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [
    heroui({
      defaultTheme: 'dark',
      themes: {
        dark: {
          colors: {
            background: '#000000',
            foreground: '#f4f4f6',
            content1: '#0e0e12',
            content2: '#141419',
            content3: '#1b1b22',
            content4: '#23232c',
            divider: 'rgba(255, 255, 255, 0.08)',
            focus: '#ffffff',
            default: {
              50: '#0a0a0d',
              100: '#131317',
              200: '#1c1c22',
              300: '#272730',
              400: '#71717e',
              500: '#a1a1ae',
              600: '#d4d4dc',
              700: '#e4e4eb',
              800: '#f4f4f7',
              900: '#ffffff',
              DEFAULT: '#1c1c22',
              foreground: '#f4f4f6',
            },
            primary: {
              50: '#ffffff',
              100: '#f4f4f5',
              200: '#e4e4e7',
              300: '#d4d4d8',
              400: '#a1a1aa',
              500: '#ffffff',
              600: '#e4e4e7',
              700: '#d4d4d8',
              800: '#a1a1aa',
              900: '#71717a',
              DEFAULT: '#ffffff',
              foreground: '#000000',
            },
            secondary: {
              50: '#18181b',
              100: '#27272a',
              DEFAULT: '#27272a',
              foreground: '#ffffff',
            },
            success: {
              DEFAULT: '#10b981',
              foreground: '#ffffff',
            },
            warning: {
              DEFAULT: '#f59e0b',
              foreground: '#000000',
            },
            danger: {
              DEFAULT: '#ef4444',
              foreground: '#ffffff',
            },
          },
        },
        light: {
          colors: {
            background: '#fafafa',
            foreground: '#09090b',
            content1: '#ffffff',
            content2: '#f4f4f5',
            content3: '#e4e4e7',
            divider: 'rgba(0, 0, 0, 0.08)',
            focus: '#09090b',
            primary: {
              DEFAULT: '#09090b',
              foreground: '#ffffff',
            },
            default: {
              DEFAULT: '#f4f4f5',
              foreground: '#09090b',
            },
          },
        },
      },
    }),
  ],
};
