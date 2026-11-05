<script setup>
// 删除数据面板：训练/体测记录列表 + 勾选删除（单条、多选、全选都走同一入口）
// 弹窗必须 append-to-body：侧栏 .glass 的 backdrop-filter 会劫持 position:fixed
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteBodyMetric,
  deleteTrainingLog,
  listBodyMetrics,
  listTrainingLogs,
} from '../api'

const props = defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue'])
const visible = ref(props.modelValue)

// v-model 双向同步：immediate 兼容组件挂载时弹窗已是打开态的情况（如 HMR 热替换）
watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
    if (v) load() // 每次打开都拉最新，别让面板显示陈旧数据
  },
  { immediate: true }
)
watch(visible, (v) => emit('update:modelValue', v))

const tab = ref('training')
const trainings = ref([])
const metrics = ref([])
const selTraining = ref([])
const selMetrics = ref([])

const load = async () => {
  ;[trainings.value, metrics.value] = await Promise.all([
    listTrainingLogs(),
    listBodyMetrics(),
  ])
}

const currentSel = () =>
  tab.value === 'training' ? selTraining.value : selMetrics.value

const removeSelected = async () => {
  const sel = currentSel()
  if (!sel.length) {
    ElMessage.warning('请先勾选要删除的记录')
    return
  }
  const label = tab.value === 'training' ? '训练记录' : '体测记录'
  try {
    await ElMessageBox.confirm(
      `将删除选中的 ${sel.length} 条${label}，不可恢复，确定执行吗？`,
      '删除记录',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return // 勾选已是第一层确认，这里二次确认即放行
  }
  const del = tab.value === 'training' ? deleteTrainingLog : deleteBodyMetric
  await Promise.all(sel.map((r) => del(r.id)))
  ElMessage.success(`已删除 ${sel.length} 条${label}`)
  await load()
}

// 80.0 显示成 80，80.5 保留一位
const fmt = (v) =>
  v === null || v === undefined ? '-' : v % 1 === 0 ? String(v) : v.toFixed(1)
</script>

<template>
  <el-dialog v-model="visible" title="删除数据" width="720px" align-center append-to-body>
    <el-tabs v-model="tab">
      <el-tab-pane :label="`训练记录（${trainings.length}）`" name="training">
        <el-table
          :data="trainings"
          height="360"
          size="small"
          @selection-change="(s) => (selTraining = s)"
        >
          <el-table-column type="selection" width="42" />
          <el-table-column prop="log_date" label="日期" width="96" />
          <el-table-column prop="body_part" label="部位" width="60" />
          <el-table-column prop="exercise" label="动作" min-width="90" />
          <el-table-column label="重量kg" width="76">
            <template #default="{ row }">{{ fmt(row.weight_kg) }}</template>
          </el-table-column>
          <el-table-column prop="sets" label="组" width="48" />
          <el-table-column prop="reps" label="次" width="48" />
          <el-table-column label="总容量kg" width="88">
            <template #default="{ row }">{{ fmt(row.volume_kg) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="`体测记录（${metrics.length}）`" name="metrics">
        <el-table
          :data="metrics"
          height="360"
          size="small"
          @selection-change="(s) => (selMetrics = s)"
        >
          <el-table-column type="selection" width="42" />
          <el-table-column prop="log_date" label="日期" width="110" />
          <el-table-column label="体重kg" width="110">
            <template #default="{ row }">{{ fmt(row.weight_kg) }}</template>
          </el-table-column>
          <el-table-column label="腰围cm" min-width="110">
            <template #default="{ row }">{{ fmt(row.waist_cm) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <div class="foot">
        <span class="hint">已选 {{ currentSel().length }} 条 · 勾选可删单条，表头勾选即全选</span>
        <el-button type="danger" plain @click="removeSelected">删除选中</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
