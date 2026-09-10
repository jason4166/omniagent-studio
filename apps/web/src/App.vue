<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue'
import { ApiClient } from './api/client'
import type { Role } from './api/types'
import ChatWorkspace from './components/ChatWorkspace.vue'
const AdminWorkspace = defineAsyncComponent(() => import('./components/AdminWorkspace.vue'))

const role = ref<Role>('member')
const page = ref('chat')
const api = computed(() => new ApiClient(role.value))
</script>

<template>
  <div class="studio">
    <aside class="rail">
      <a class="brand" href="#" aria-label="OmniAgent Studio 首页" @click.prevent="page = 'chat'">
        <span class="brand-symbol">O<span>·</span></span
        ><span>omniagent<span class="brand-sub">STUDIO</span></span>
      </a>
      <div class="nav-caption">WORKSPACE</div>
      <button class="nav-item" :class="{ active: page === 'chat' }" @click="page = 'chat'">
        <span>◈</span> Agent 工作台
      </button>
      <button
        v-if="role === 'admin'"
        class="nav-item"
        :class="{ active: page === 'admin' }"
        @click="page = 'admin'"
      >
        <span>▦</span> 配置与管理
      </button>
      <div class="rail-note">
        <span class="status-dot"></span> 本地演示环境
        <p>有依据的回答<br />可审批的行动<br />可恢复的会话</p>
        <span class="small">OMNIAGENT / v1.0 RC</span>
      </div>
    </aside>
    <div class="main-shell">
      <header class="topbar">
        <div class="breadcrumb">
          Studio <span>/</span> {{ page === 'chat' ? 'Agent 工作台' : '配置与管理' }}
        </div>
        <div class="identity">
          <el-button
            v-if="role === 'admin'"
            class="mobile-nav"
            size="small"
            @click="page = page === 'chat' ? 'admin' : 'chat'"
            >{{ page === 'chat' ? '管理' : '工作台' }}</el-button
          >
          <span class="environment-badge">DEV IDENTITY</span
          ><el-select
            v-model="role"
            aria-label="开发身份"
            style="width: 142px"
            @change="page = 'chat'"
            ><el-option label="成员 · Member" value="member" /><el-option
              label="管理员 · Admin"
              value="admin" /><el-option label="访客 · Viewer" value="viewer"
          /></el-select>
        </div>
      </header>
      <main :key="role">
        <ChatWorkspace v-if="page === 'chat'" :api="api" />
        <AdminWorkspace v-else :api="api" />
      </main>
    </div>
  </div>
</template>
