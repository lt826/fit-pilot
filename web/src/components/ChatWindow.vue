<script setup>
// 对话流：维护消息列表，消费 SSE 事件并把过程信息挂到对应消息上
import { nextTick, onMounted, reactive, ref } from 'vue'
import { streamChat } from '../api'
import ElectricBorder from './ElectricBorder.vue'
import MessageBubble from './MessageBubble.vue'

const emit = defineEmits(['profile-updated', 'turn-finished'])
const props = defineProps({ sessionId: { type: String, default: '' } })

const messages = ref([
  {
    role: 'assistant',
    text: '你好，我是 FitPilot 💪 可以问我健身知识（附出处）、帮你记录训练和体重、查食物热量——试试左侧的快捷演示。',
    route: '',
    tools: [],
    citations: [],
    notice: '',
    streaming: false,
  },
])
const input = ref('')
const busy = ref(false)
const sessionId = ref(props.sessionId)
const listRef = ref(null)

// 历史会话切换入口：父组件调用，整体替换消息列表（历史消息不含过程轨迹）
function loadSession(id, msgs) {
  sessionId.value = id
  messages.value =
    msgs && msgs.length
      ? msgs
      : [
          {
            role: 'assistant',
            text: '你好，我是 FitPilot 💪 可以问我健身知识（附出处）、帮你记录训练和体重、查食物热量——试试左侧的快捷演示。',
            route: '',
            tools: [],
            citations: [],
            notice: '',
            streaming: false,
          },
        ]
  nextTick(scrollToBottom)
}

const scrollToBottom = () => {
  nextTick(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function send(text) {
  const message = (text ?? input.value).trim()
  if (!message || busy.value) return
  input.value = ''
  busy.value = true

  messages.value.push({
    role: 'user', text: message, route: '', tools: [], citations: [], notice: '', streaming: false,
  })
  // 必须用 reactive 包装：SSE 回调高频修改该对象的属性（text/route/tools…），
  // 若 push 的是普通对象、再通过原始引用修改，会绕过 Vue3 的响应式代理，
  // 界面不重渲染（表现为流式内容卡住不更新）——Vue3 经典陷阱
  const assistant = reactive({
    role: 'assistant', text: '', route: '', tools: [], citations: [], notice: '', streaming: true,
  })
  messages.value.push(assistant)
  scrollToBottom()

  try {
    await streamChat(message, sessionId.value, {
      session: (d) => (sessionId.value = d.session_id),
      route: (d) => (assistant.route = d.route),
      tool_call: (d) => assistant.tools.push(d),
      citation: (d) => (assistant.citations = d.sources),
      delta: (d) => {
        assistant.text += d.text
        scrollToBottom()
      },
      notice: (d) => {
        assistant.notice = d.text
        emit('profile-updated')
      },
      error: (d) => (assistant.text += `\n⚠ ${d.message}`),
    })
  } catch (e) {
    assistant.text += `\n⚠ ${e.message}`
  } finally {
    assistant.streaming = false
    busy.value = false
    scrollToBottom()
    emit('turn-finished') // 通知父组件刷新历史列表（标题/时间已更新）
  }
}

defineExpose({ send, loadSession })
onMounted(scrollToBottom)
</script>

<template>
  <div class="chat">
    <div ref="listRef" class="list">
      <MessageBubble
        v-for="(m, i) in messages"
        :key="i"
        :msg="m"
      />
    </div>
    <div class="composer-wrap">
      <!-- 电流边框（ReactBits ElectricBorder 的 Vue 移植）：
           画布向外溢出 64px 属预期，glow 会叠在消息区上（pointer-events 穿透） -->
      <ElectricBorder
        :border-radius="14"
        color="#7df9ff"
        glow-color="#22d3ee"
        :thickness="1.3"
        :chaos="0.55"
        :spread="0.6"
        :strands="3"
        :glow="0.75"
        :intensity="0.9"
        :arcs="1"
        :speed="1"
      >
        <div class="composer">
          <el-input
            v-model="input"
            placeholder="输入问题，回车发送…"
            :disabled="busy"
            @keyup.enter="send()"
          />
          <el-button type="primary" :loading="busy" @click="send()">发送</el-button>
        </div>
      </ElectricBorder>
    </div>
  </div>
</template>

<style scoped>
.chat {
  height: 100%;
  display: flex;
  flex-direction: column;
  /* 电流画布向四周溢出 64px：顶部溢出是刻意的光晕叠层（在 .chat 内部，不受影响），
     但底部/左右溢出会撑大页面滚动区，产生多余的页面级滚动条——这里整体裁掉 */
  overflow: hidden;
}
.list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 20px 24px;
}
/* 外层留出电流 glow 的呼吸空间（画布上下溢出 64px） */
.composer-wrap {
  padding: 14px 20px 18px;
}
.composer {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 14px;
  background: var(--el-bg-color-overlay);
}
</style>
