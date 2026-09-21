<script setup lang="ts">
const recordNumber = import.meta.env.VITE_ICP_RECORD_NUMBER?.trim() ?? ''
</script>

<template>
  <footer v-if="recordNumber" class="site-footer">
    <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">
      {{ recordNumber }}
    </a>
  </footer>
</template>

<style scoped>
.site-footer {
  padding: 16px 24px;
  text-align: center;
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
}
.site-footer a {
  color: inherit;
  text-decoration: none;
}
.site-footer a:hover {
  color: #087f75;
  text-decoration: underline;
}
</style>
