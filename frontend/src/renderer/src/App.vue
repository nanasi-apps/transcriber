<script setup lang="ts">
import TranscribeView from './components/TranscribeView.vue'
</script>

<template>
  <div class="app">
    <TranscribeView />
  </div>
</template>

<style>
:root {
  color-scheme: light;
  --page-ivory: #fcf7f1;
  --page-mist: #eef2f7;
  --surface-card: rgba(255, 255, 255, 0.82);
  --surface-muted: rgba(248, 250, 252, 0.78);
  --border-soft: rgba(135, 148, 166, 0.26);
  --border-strong: rgba(72, 96, 124, 0.18);
  --text-strong: #1b2430;
  --text-body: #485467;
  --text-muted: #6b7688;
  --accent-navy: #26415c;
  --accent-gold: #c88e48;
  --accent-sage: #75907f;
  --accent-rose: #c46b52;
  --success-bg: #e6f5ec;
  --success-text: #246246;
  --warning-bg: #fef1da;
  --warning-text: #8d5c1f;
  --danger-bg: #fdeaea;
  --danger-text: #a63f3f;
  --info-bg: #e8f0fb;
  --info-text: #30568a;
  --shadow-card: 0 24px 70px rgba(23, 35, 52, 0.12);
}

*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html,
body,
#app {
  height: 100%;
}

body {
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif,
    'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol';
  color: #111827;
  background-color: #f9fafb; /* Standard light gray like tailwind bg-gray-50 */
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.app {
  height: 100%;
  display: flex;
  flex-direction: column;
}

button,
input,
textarea,
select {
  font: inherit;
}
</style>
