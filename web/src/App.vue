<script setup>
// 顶层布局：左侧画像+快捷演示，中间对话流，右侧历史会话；Aurora 极光背景铺底
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import AuroraBg from './components/AuroraBg.vue'
import ChatWindow from './components/ChatWindow.vue'
import HistoryPanel from './components/HistoryPanel.vue'
import ProfileCard from './components/ProfileCard.vue'
import DataManager from './components/DataManager.vue'
import {
  createSession,
  deleteSession,
  getProfile,
  getSessionMessages,
  getToken,
  listSessions,
  login,
} from './api'

const profile = ref(null)
const chatRef = ref(null)
const sessions = ref([])
const activeId = ref('')
const dataMgrOpen = ref(false)

// ---- 登录态 ----
const loggedIn = ref(!!getToken())
const password = ref('')
const logging = ref(false)
const doLogin = async () => {
  if (!password.value) return
  logging.value = true
  try {
    await login(password.value)
    loggedIn.value = true
    password.value = ''
    ElMessage.success('登录成功')
    onMountedInit()
  } catch (e) {
    ElMessage.error(e.message || '登录失败')
  } finally {
    logging.value = false
  }
}
// token 过期/失效：任何接口 401 时弹回登录层
window.addEventListener('fitpilot:unauthorized', () => {
  loggedIn.value = false
})

const refreshProfile = async () => {
  profile.value = await getProfile()
}
const refreshSessions = async () => {
  sessions.value = await listSessions()
}

// 刷新/首次进入：默认新建一个会话（产品要求，对标 DeepSeek 行为）
const newSession = async () => {
  const r = await createSession()
  activeId.value = r.session_id
  chatRef.value?.loadSession(r.session_id, [])
  await refreshSessions()
}

const selectSession = async (id) => {
  if (id === activeId.value) return
  const msgs = await getSessionMessages(id)
  activeId.value = id
  chatRef.value?.loadSession(
    id,
    msgs.map((m) => ({
      role: m.role,
      text: m.content,
      route: m.route || '',
      tools: [],
      citations: [],
      notice: '',
      streaming: false,
    }))
  )
}

const removeSession = async (id) => {
  await deleteSession(id)
  if (id === activeId.value) await newSession()
  else await refreshSessions()
}

// 预置演示问题：面试/录屏时一键触发四条链路
const quickAsks = [
  { label: '⚙ 记录训练', text: '帮我记录今天硬拉80公斤3组每组5次' },
  { label: '📚 知识问答', text: '新手应该先练哪些动作？' },
  { label: '🔀 混合场景', text: '我这周练了几次腿？会不会太频繁？' },
  { label: '🚫 域外拒答', text: 'Python爬虫怎么写？' },
]
const quickAsk = (text) => chatRef.value?.send(text)

const onMountedInit = async () => {
  await refreshProfile()
  await newSession()
}

onMounted(async () => {
  if (!loggedIn.value) return
  // 用真实接口验 token 是否仍有效
  try {
    await getProfile()
  } catch {
    return
  }
  await onMountedInit()
})
</script>

<template>
  <AuroraBg v-if="loggedIn" />
  <el-container v-if="loggedIn" class="layout">
    <el-aside width="280px" class="aside glass">
      <div class="brand">
        <span class="logo">💪</span>
        <div>
          <div class="title">FitPilot</div>
          <div class="subtitle">RAG + Agent 健身私教</div>
        </div>
      </div>

      <ProfileCard :profile="profile" @saved="refreshProfile" />

      <div class="quick">
        <div class="quick-title">快捷演示</div>
        <el-button
          v-for="q in quickAsks"
          :key="q.label"
          class="quick-btn"
          size="small"
          @click="quickAsk(q.text)"
        >
          {{ q.label }}
        </el-button>
      </div>

      <div class="danger-zone">
        <el-button size="small" text type="danger" @click="dataMgrOpen = true">
          🗑 删除数据
        </el-button>
      </div>

      <DataManager v-model="dataMgrOpen" />
    </el-aside>

    <el-main class="main">
      <ChatWindow
        ref="chatRef"
        :session-id="activeId"
        @profile-updated="refreshProfile"
        @turn-finished="refreshSessions"
      />
    </el-main>

    <el-aside width="240px" class="aside right glass">
      <HistoryPanel
        :sessions="sessions"
        :active-id="activeId"
        @create="newSession"
        @select="selectSession"
        @remove="removeSession"
      />
    </el-aside>
  </el-container>

<!-- 登录层：口令换 JWT（深空电光配色） -->
<div v-else class="login-mask">
  <div class="login-card">
    <div class="login-logo">💪</div>
    <div class="login-title">FitPilot</div>
    <div class="login-sub">RAG + Agent 健身私教</div>
    <el-input
      v-model="password"
      type="password"
      placeholder="访问口令"
      size="large"
      show-password
      @keydown.enter="doLogin"
    />
    <el-button type="primary" size="large" class="login-btn" :loading="logging" @click="doLogin">
      进 入
    </el-button>
  </div>
</div>
</template>

<style>
/* ---- 深空电光主题：覆盖 Element Plus 深色变量 ---- */
html.dark {
  --el-color-primary: #22d3ee;
  --el-color-primary-dark-2: #48dcef;
  --el-color-primary-light-3: #1e98a8;
  --el-color-primary-light-5: #1b7881;
  --el-color-primary-light-7: #185761;
  --el-color-primary-light-8: #184750;
  --el-color-primary-light-9: #163f44;
  --el-bg-color: #0d1420;
  --el-bg-color-overlay: #121a2b;
  --el-border-color: #263449;
  --el-border-color-light: #1f2c40;
  --el-fill-color-light: #16202f;
}
body {
  margin: 0;
  background: #0d1420;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
</style>

<style scoped>
.layout {
  height: 100vh;
  position: relative;
  z-index: 1; /* 铺在 Aurora(固定层 z-index:0)之上 */
}
.aside {
  border-right: 1px solid var(--el-border-color-light);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
}
.aside.right {
  border-right: none;
  border-left: 1px solid var(--el-border-color-light);
  padding: 0;
}
/* 半透明玻璃面板：让极光从背景透出来 */
.glass {
  background: color-mix(in srgb, var(--el-bg-color) 82%, transparent);
  backdrop-filter: blur(14px);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.logo {
  font-size: 30px;
  filter: drop-shadow(0 0 10px rgba(34, 211, 238, 0.6));
}
.title {
  font-weight: 700;
  font-size: 18px;
  background: linear-gradient(90deg, #7df9ff, #22d3ee, #8b5cf6);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.subtitle {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.quick-title {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}
.quick {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.quick-btn {
  justify-content: flex-start;
}
/* 清空按钮沉底：不可逆操作不与常用功能抢位置 */
.danger-zone {
  margin-top: auto;
}
.main {
  padding: 0;
}
</style>

<style scoped>
.login-mask {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(ellipse at 50% 30%, #16233f 0%, #0d1420 65%);
}
.login-card {
  width: 330px;
  background: rgba(18, 26, 43, 0.92);
  border: 1px solid var(--el-border-color);
  border-radius: 14px;
  padding: 34px 30px 30px;
  text-align: center;
  box-shadow: 0 0 40px rgba(34, 211, 238, 0.15);
}
.login-logo {
  font-size: 40px;
  filter: drop-shadow(0 0 12px rgba(34, 211, 238, 0.6));
}
.login-title {
  font-size: 22px;
  font-weight: 700;
  margin-top: 8px;
  background: linear-gradient(90deg, #7df9ff, #22d3ee, #8b5cf6);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.login-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 4px 0 22px;
}
.login-btn {
  width: 100%;
  margin-top: 14px;
}
</style>
