<script setup lang="ts">
import { businessValue, fieldLabel } from '../api/businessPresentation'
import type { Json } from '../api/types'

defineProps<{ values: Record<string, Json> }>()
</script>

<template>
  <div class="business-fields">
    <dl v-if="Object.keys(values).length" class="business-field-list">
      <div v-for="(value, key) in values" :key="key">
        <dt>{{ fieldLabel(key) }}</dt>
        <dd>{{ businessValue(value, key) }}</dd>
      </div>
    </dl>
    <p v-else class="small">没有需要展示的信息。</p>
    <details class="business-raw">
      <summary>查看原始数据</summary>
      <pre class="code-block">{{ JSON.stringify(values, null, 2) }}</pre>
    </details>
  </div>
</template>

<style scoped>
.business-field-list {
  display: grid;
  gap: 12px;
  margin: 14px 0;
}
.business-field-list > div {
  display: grid;
  grid-template-columns: minmax(90px, 0.3fr) minmax(0, 1fr);
  gap: 16px;
}
dt {
  color: #60747d;
  font-size: 12px;
}
dd {
  margin: 0;
  color: #23404a;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
}
.business-raw {
  margin: 10px 0;
  color: #60747d;
  font-size: 11px;
}
summary {
  cursor: pointer;
}
</style>
