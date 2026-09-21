<script setup lang="ts">
import { computed } from 'vue'
import { toolLabel } from '../api/businessPresentation'
import type { Json, OperationRecord } from '../api/types'
import BusinessFields from './BusinessFields.vue'

const props = defineProps<{ operation: Omit<OperationRecord, 'run_id'> }>()
const values = computed<Record<string, Json>>(() => {
  const data = props.operation.data
  return data !== null && typeof data === 'object' && !Array.isArray(data)
    ? data
    : { content: data }
})
const status = computed(() => {
  const labels = { succeeded: '已完成', failed: '执行失败', rejected: '未执行' }
  return Object.hasOwn(labels, props.operation.status)
    ? labels[props.operation.status]
    : '状态待确认'
})
</script>

<template>
  <details class="tool-summary execution-record">
    <summary>{{ toolLabel(operation.tool_name) }} · 执行记录</summary>
    <p class="small">执行状态：{{ status }}</p>
    <h4>返回信息</h4>
    <BusinessFields :values="values" />
    <h4>操作参数</h4>
    <BusinessFields :values="operation.arguments" />
  </details>
</template>
