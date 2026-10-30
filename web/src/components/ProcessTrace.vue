<script setup>
// 执行过程轨迹：路由标签 + 工具调用 + 知识引用 —— 本项目前端的灵魂组件
import { computed } from 'vue'

const props = defineProps({
  route: { type: String, default: '' },
  tools: { type: Array, default: () => [] },
  citations: { type: Array, default: () => [] },
  streaming: { type: Boolean, default: false },
})

const ROUTE_META = {
  chat: { label: '闲聊', type: 'info' },
  knowledge: { label: '知识问答 · RAG', type: 'primary' },
  task: { label: '任务执行 · 工具', type: 'warning' },
  mixed: { label: '混合 · 工具+检索', type: 'danger' },
}

const routeMeta = computed(() => ROUTE_META[props.route])

// args 是 JSON 字符串，展示时截短保持一行
const shortArgs = (a) => {
  try {
    const obj = JSON.parse(a)
    const s = JSON.stringify(obj)
    return s.length > 60 ? s.slice(0, 60) + '…' : s
  } catch {
    return a
  }
}
</script>

<template>
  <div v-if="route || tools.length || citations.length" class="trace">
    <el-tag v-if="routeMeta" :type="routeMeta.type" size="small" effect="plain">
      ⟳ {{ routeMeta.label }}
    </el-tag>

    <div v-for="(t, i) in tools" :key="i" class="tool-line">
      <span class="tool-name">⚙ {{ t.tool }}</span>
      <span class="tool-args">{{ shortArgs(t.args) }}</span>
      <el-tooltip :content="t.result" placement="top" :show-after="300">
        <span class="tool-ok">✓</span>
      </el-tooltip>
    </div>

    <div v-if="citations.length" class="cites">
      <div v-for="(c, i) in citations" :key="i" class="cite">📚 {{ c }}</div>
    </div>

    <el-divider v-if="route || tools.length" class="sep" />
  </div>
</template>

<style scoped>
.trace {
  margin-bottom: 6px;
}
.tool-line {
  font-size: 12px;
  margin-top: 4px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.tool-name {
  color: var(--el-color-warning-dark-2);
  font-family: Consolas, monospace;
}
.tool-args {
  color: var(--el-text-color-secondary);
  font-family: Consolas, monospace;
  word-break: break-all;
}
.tool-ok {
  color: var(--el-color-success);
  cursor: help;
}
.cites {
  margin-top: 4px;
}
.cite {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.sep {
  margin: 8px 0 6px;
}
</style>
