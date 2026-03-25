<script setup lang="ts">
import TranscribeView from './components/TranscribeView.vue'
</script>

<template>
  <div class="app">
    <TranscribeView />
  </div>
</template>

<style>
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
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', sans-serif;
  color: #1a1a1a;
  background:
    radial-gradient(circle at top, #f6f0e6 0%, #fbfaf7 40%, #f4f6fb 100%);
  -webkit-font-smoothing: antialiased;
}

.app {
  height: 100%;
  display: flex;
  flex-direction: column;
}
</style>
