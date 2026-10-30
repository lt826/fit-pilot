<script setup>
// 单条消息气泡：用户右侧，助手左侧（含执行过程轨迹 + 流式光标）
import ProcessTrace from './ProcessTrace.vue'

defineProps({ msg: { type: Object, required: true } })
</script>

<template>
  <div class="row" :class="msg.role">
    <div class="bubble" :class="msg.role">
      <template v-if="msg.role === 'assistant'">
        <ProcessTrace
          :route="msg.route"
          :tools="msg.tools"
          :citations="msg.citations"
          :streaming="msg.streaming && !msg.text"
        />
      </template>

      <div class="text">
        {{ msg.text }}<span v-if="msg.streaming && msg.text" class="cursor">▌</span>
        <span v-if="msg.streaming && !msg.text" class="dots">思考中…</span>
      </div>

      <el-alert
        v-if="msg.notice"
        :title="msg.notice"
        type="success"
        :closable="false"
        class="notice"
      />
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  margin-bottom: 14px;
}
.row.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 12px;
  line-height: 1.65;
  font-size: 14px;
}
.bubble.user {
  background: linear-gradient(135deg, #22d3ee, #0ea5b7);
  color: #05202a; /* 青色底配深字，对比度优于白字 */
  font-weight: 500;
  border-bottom-right-radius: 4px;
  box-shadow: 0 0 14px rgba(34, 211, 238, 0.25);
}
.bubble.assistant {
  background: var(--el-fill-color-light);
  border-bottom-left-radius: 4px;
}
.text {
  white-space: pre-wrap;
  word-break: break-word;
}
.cursor {
  animation: blink 0.9s infinite;
}
.dots {
  color: var(--el-text-color-secondary);
}
.notice {
  margin-top: 8px;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
</style>
