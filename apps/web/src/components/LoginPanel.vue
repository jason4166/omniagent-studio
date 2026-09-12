<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiClient } from '../api/client'
import type { UserIdentity } from '../api/types'
const props = defineProps<{ api: ApiClient }>()
const emit = defineEmits<{ authenticated: [user: UserIdentity] }>()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const publicLogin = ref<{ username: string; password: string } | null>(null)
const prefilled = ref(false)
let edited = false
function markEdited() {
  edited = true
  prefilled.value = false
}
onMounted(async () => {
  try {
    const options = await props.api.authOptions()
    publicLogin.value = options.public_login
    if (!edited && !loading.value && !username.value && !password.value && options.public_login) {
      username.value = options.public_login.username
      password.value = options.public_login.password
      prefilled.value = true
    }
  } catch {
    // A missing optional public entry does not prevent ordinary account login.
  }
})
async function submit() {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    emit('authenticated', (await props.api.login(username.value.trim(), password.value)).user)
  } catch {
    error.value = '登录失败，请检查账号和密码；尝试过多时请稍后重试。'
  } finally {
    if (
      username.value !== publicLogin.value?.username ||
      password.value !== publicLogin.value?.password
    )
      password.value = ''
    loading.value = false
  }
}
</script>
<template>
  <div class="login-shell">
    <div class="login-intro">
      <span class="eyebrow">OMNIAGENT STUDIO</span>
      <h1>欢迎使用</h1>
      <p>登录后选择助手，开始或继续你的对话。</p>
    </div>
    <el-card class="login-card">
      <h2>登录工作台</h2>
      <p class="small">
        {{ prefilled ? '体验账号已填入，也可使用你的账号登录。' : '使用你的账号登录。' }}
      </p>
      <form @submit.prevent="submit">
        <el-form-item label="账号"
          ><el-input
            v-model="username"
            aria-label="账号"
            autocomplete="username"
            maxlength="64"
            required
            @update:model-value="markEdited"
        /></el-form-item>
        <el-form-item label="密码"
          ><el-input
            v-model="password"
            aria-label="密码"
            type="password"
            autocomplete="current-password"
            maxlength="256"
            required
            show-password
            @update:model-value="markEdited"
        /></el-form-item>
        <el-alert v-if="error" :title="error" type="error" :closable="false" role="alert" />
        <el-button
          type="primary"
          native-type="submit"
          :loading="loading"
          :disabled="!username || !password"
          style="width: 100%; margin-top: 20px"
          >登录</el-button
        >
      </form>
    </el-card>
  </div>
</template>
<style scoped>
.login-shell {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 80px;
  padding: 32px;
  background: #f2f5f8;
}
.login-intro h1 {
  font-size: 42px;
  line-height: 1.4;
  color: #17372f;
}
.login-intro p {
  color: #64748b;
  max-width: 360px;
  line-height: 1.8;
}
.login-card {
  width: 380px;
  padding: 20px;
}
.login-card h2 {
  margin-top: 0;
}
.login-card .small {
  margin-bottom: 28px;
}
.eyebrow {
  letter-spacing: 3px;
  color: #16735c;
  font-weight: 700;
}
@media (max-width: 800px) {
  .login-shell {
    flex-direction: column;
    gap: 20px;
  }
  .login-intro h1 {
    font-size: 28px;
  }
  .login-card {
    width: 100%;
    max-width: 420px;
  }
}
</style>
