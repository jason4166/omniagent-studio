<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiClient } from './api/client'
import type { UserIdentity } from './api/types'
import LoginPanel from './components/LoginPanel.vue'
import AccountManager from './components/AccountManager.vue'
import PasswordDialog from './components/PasswordDialog.vue'
import ChatWorkspace from './components/ChatWorkspace.vue'
const AdminWorkspace = defineAsyncComponent(() => import('./components/AdminWorkspace.vue'))

const user = ref<UserIdentity | null>(null)
const initialized = ref(false)
const role = computed(() => user.value?.role)
const canViewManagement = computed(() => role.value === 'admin' || role.value === 'reviewer')
const roleLabel = computed(() => {
  return { admin: '管理员', reviewer: '管理只读', viewer: '访客', member: '成员' }[
    role.value ?? 'member'
  ]
})
const api = new ApiClient(globalThis.fetch.bind(globalThis), () => {
  user.value = null
})
onMounted(async () => {
  try {
    user.value = (await api.me()).user
  } catch {
    user.value = null
  } finally {
    initialized.value = true
  }
})
async function logout() {
  try {
    await api.logout()
    user.value = null
    page.value = 'chat'
  } catch {
    ElMessage.error('尚未退出登录，请重试。')
  }
}
const page = ref('chat')
function authenticated(identity: UserIdentity) {
  user.value = identity
  page.value = 'chat'
}
</script>

<template>
  <div v-if="!initialized" role="status" style="padding: 48px">正在恢复登录…</div>
  <LoginPanel v-else-if="!user" :api="api" @authenticated="authenticated" />
  <div v-else class="studio">
    <aside class="rail">
      <a class="brand" href="#" aria-label="OmniAgent Studio 首页" @click.prevent="page = 'chat'">
        <span class="brand-symbol">O<span>·</span></span
        ><span>omniagent<span class="brand-sub">STUDIO</span></span>
      </a>
      <div class="nav-caption">工作区</div>
      <button class="nav-item" :class="{ active: page === 'chat' }" @click="page = 'chat'">
        <span>◈</span> 工作台
      </button>
      <button
        v-if="canViewManagement"
        class="nav-item"
        :class="{ active: page === 'admin' }"
        @click="page = 'admin'"
      >
        <span>▦</span> 配置与管理
      </button>
      <button
        v-if="role === 'admin'"
        class="nav-item"
        :class="{ active: page === 'accounts' }"
        @click="page = 'accounts'"
      >
        账号与访问
      </button>
      <div v-if="role === 'admin'" class="rail-note">
        <span class="small">OMNIAGENT / v1.0 RC</span>
      </div>
    </aside>
    <div class="main-shell">
      <header class="topbar">
        <div class="breadcrumb">
          工作区 <span>/</span>
          {{ page === 'chat' ? '工作台' : page === 'accounts' ? '账号与访问' : '配置与管理' }}
        </div>
        <div class="identity">
          <el-button
            v-if="canViewManagement"
            class="mobile-nav"
            size="small"
            @click="page = page === 'chat' ? 'admin' : 'chat'"
            >{{ page === 'chat' ? '管理' : '工作台' }}</el-button
          >
          <span class="environment-badge">{{ roleLabel }}</span
          ><PasswordDialog v-if="!user.is_public_guest" :api="api" /><el-button @click="logout"
            >退出登录</el-button
          >
        </div>
      </header>
      <main :key="user.user_id">
        <ChatWorkspace v-if="page === 'chat'" :api="api" />
        <AccountManager v-else-if="page === 'accounts' && role === 'admin'" :api="api" />
        <AdminWorkspace v-else-if="canViewManagement" :api="api" :readonly="role === 'reviewer'" />
      </main>
    </div>
  </div>
</template>
