<script setup>
// 右侧历史会话面板：新建 / 切换 / 删除（对标 DeepSeek/智谱 的会话列表）
defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
})
defineEmits(['create', 'select', 'remove'])

const fmtTime = (t) => (t || '').slice(5, 16).replace('T', ' ')
</script>

<template>
  <div class="history">
    <div class="head">
      <span>🕘 对话历史</span>
      <el-button size="small" type="primary" plain @click="$emit('create')">
        ＋ 新建
      </el-button>
    </div>

    <div class="empty" v-if="!sessions.length">暂无历史对话</div>

    <div
      v-for="s in sessions"
      :key="s.session_id"
      class="item"
      :class="{ active: s.session_id === activeId }"
      @click="$emit('select', s.session_id)"
    >
      <div class="title">{{ s.title }}</div>
      <div class="meta">{{ s.messages }} 条 · {{ fmtTime(s.updated_at) }}</div>
      <span
        class="del"
        title="删除会话"
        @click.stop="$emit('remove', s.session_id)"
      >✕</span>
    </div>
  </div>
</template>

<style scoped>
.history {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 14px 10px;
  overflow-y: auto;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  margin-bottom: 10px;
  padding: 0 4px;
}
.empty {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  text-align: center;
  padding: 20px 0;
}
.item {
  position: relative;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  padding-right: 26px;
}
.item:hover {
  background: var(--el-fill-color);
}
.item.active {
  background: var(--el-color-primary-light-9);
}
.title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
.del {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 12px;
  color: var(--el-text-color-secondary);
  visibility: hidden;
}
.item:hover .del {
  visibility: visible;
}
.del:hover {
  color: var(--el-color-danger);
}
</style>
