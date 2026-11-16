<script setup>
// 单条消息气泡：用户右侧，助手左侧（含执行过程轨迹 + 流式光标）
// 助手回答按 Markdown 渲染（模型常用 **加粗**/列表），DOMPurify 消毒防注入
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import ProcessTrace from './ProcessTrace.vue'

const props = defineProps({ msg: { type: Object, required: true } })

marked.setOptions({ breaks: true }) // 模型回答常单行成句，单换行转 <br>

const rendered = computed(() =>
  DOMPurify.sanitize(marked.parse(props.msg.text || '')))
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

      <div v-if="msg.role === 'assistant'" class="text md">
        <span v-html="rendered"></span><span v-if="msg.streaming && msg.text" class="cursor">▌</span>
        <span v-if="msg.streaming && !msg.text" class="dots">思考中…</span>
      </div>
      <div v-else class="text">{{ msg.text }}</div>

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
/* v-html 渲染出的 markdown 元素（scoped 下要 :deep） */
.md :deep(strong) {
  color: #7df9ff;
}
.md :deep(ul), .md :deep(ol) {
  margin: 6px 0;
  padding-left: 20px;
}
.md :deep(li) {
  margin: 2px 0;
}
.md :deep(h1), .md :deep(h2), .md :deep(h3) {
  font-size: 15px;
  margin: 8px 0 4px;
}
.md :deep(p) {
  margin: 4px 0;
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
