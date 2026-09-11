<script setup lang="ts">
import { ref } from 'vue'
import { ApiClient } from '../api/client'
const props = defineProps<{ api: ApiClient }>()
const visible = ref(false)
const current = ref('')
const next = ref('')
const busy = ref(false)
const error = ref('')
function clear() {
  current.value = ''
  next.value = ''
  error.value = ''
}
async function save() {
  busy.value = true
  try {
    await props.api.changePassword(current.value, next.value)
    visible.value = false
  } catch {
    error.value = '修改失败，请检查当前密码。新密码至少 15 个字符。'
  } finally {
    current.value = ''
    next.value = ''
    busy.value = false
  }
}
</script>
<template>
  <el-button @click="visible = true">修改密码</el-button>
  <el-dialog v-model="visible" title="修改密码" width="420px" @closed="clear">
    <p>修改后所有设备的登录都会撤销，请使用新密码重新登录。</p>
    <el-form label-position="top"
      ><el-form-item label="当前密码"
        ><el-input
          v-model="current"
          aria-label="当前密码"
          type="password"
          autocomplete="current-password"
          maxlength="256" /></el-form-item
      ><el-form-item label="新密码"
        ><el-input
          v-model="next"
          aria-label="新密码"
          type="password"
          autocomplete="new-password"
          maxlength="256" /></el-form-item
    ></el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template #footer
      ><el-button
        type="primary"
        :loading="busy"
        :disabled="!current || next.length < 15"
        @click="save"
        >保存并重新登录</el-button
      ></template
    >
  </el-dialog>
</template>
