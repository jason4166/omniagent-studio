<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiClient } from '../api/client'
import type { Account, Role } from '../api/types'
const props = defineProps<{ api: ApiClient }>()
const accounts = ref<Account[]>([])
const username = ref('')
const password = ref('')
const role = ref<Role>('member')
const profiles = ref<string[]>([])
const selected = ref(['hr', 'support', 'sales'])
const busy = ref(false)
const message = ref('')
const error = ref('')
async function refresh() {
  accounts.value = await props.api.accounts()
}
onMounted(async () => {
  try {
    await refresh()
    profiles.value = (await props.api.profiles()).map((p) => p.profile_id)
  } catch {
    error.value = '无法加载账号'
  }
})
async function create() {
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    await props.api.createAccount({
      username: username.value,
      password: password.value,
      role: role.value,
      profile_ids: selected.value,
    })
    username.value = ''
    message.value = '账号已创建，请通过安全渠道交付登录信息。'
    await refresh()
  } catch {
    error.value = '创建失败：账号须唯一，密码至少 15 个字符。'
  } finally {
    password.value = ''
    busy.value = false
  }
}
async function toggle(account: Account) {
  busy.value = true
  error.value = ''
  try {
    await props.api.updateAccount(account, !account.enabled)
    await refresh()
    message.value = '状态已更新，原登录已撤销。'
  } catch {
    error.value = '更新失败，请刷新重试；最后一个管理员不能停用。'
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <section class="account-panel">
    <h1>账号与访问</h1>
    <p>每位访客使用独立账号。角色和 Profile 权限由服务端验证。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="message" :title="message" type="success" :closable="false" />
    <el-card
      ><h2>创建账号</h2>
      <el-form label-position="top" @submit.prevent="create">
        <el-form-item label="账号"
          ><el-input v-model="username" aria-label="新账号" maxlength="64"
        /></el-form-item>
        <el-form-item label="初始密码（至少 15 个字符）"
          ><el-input
            v-model="password"
            aria-label="初始密码"
            type="password"
            autocomplete="new-password"
            maxlength="256"
        /></el-form-item>
        <el-form-item label="角色"
          ><el-select v-model="role" aria-label="账号角色"
            ><el-option label="成员" value="member" /><el-option
              label="访客"
              value="viewer" /><el-option label="管理员" value="admin" /></el-select
        ></el-form-item>
        <el-form-item label="允许使用的 Profile"
          ><el-select v-model="selected" multiple aria-label="账号 Profile"
            ><el-option v-for="id in profiles" :key="id" :label="id" :value="id" /></el-select
        ></el-form-item>
        <el-button
          type="primary"
          :loading="busy"
          :disabled="!username || password.length < 15"
          @click="create"
          >创建账号</el-button
        >
      </el-form></el-card
    >
    <el-table :data="accounts" empty-text="暂无账号"
      ><el-table-column prop="username" label="账号" /><el-table-column
        prop="role"
        label="角色"
      /><el-table-column label="状态"
        ><template #default="{ row }">{{
          row.enabled ? '启用' : '停用'
        }}</template></el-table-column
      ><el-table-column label="操作"
        ><template #default="{ row }"
          ><el-button :disabled="busy" @click="toggle(row)">{{
            row.enabled ? '停用并撤销登录' : '启用'
          }}</el-button></template
        ></el-table-column
      ></el-table
    >
  </section>
</template>
<style scoped>
.account-panel {
  padding: 32px;
  max-width: 1000px;
}
.el-card {
  margin: 24px 0;
  max-width: 600px;
}
</style>
