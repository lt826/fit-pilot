<script setup>
// 用户画像卡：长期记忆的可视化（对应后端 user_profile 表）
import { reactive, ref, watch } from 'vue'
import { saveProfile } from '../api'

const props = defineProps({ profile: { type: Object, default: null } })
const emit = defineEmits(['saved'])

const dialogVisible = ref(false)
const form = reactive({})

watch(dialogVisible, (v) => {
  if (v && props.profile) Object.assign(form, props.profile)
})

const rows = [
  ['目标', () => props.profile?.goal || '未设置'],
  ['训练年限', () => (props.profile?.training_years ? props.profile.training_years + ' 年' : '未设置')],
  ['身高/体重', () =>
    props.profile?.height_cm || props.profile?.weight_kg
      ? `${props.profile?.height_cm || '-'}cm / ${props.profile?.weight_kg || '-'}kg`
      : '未设置'],
  ['伤病史', () => props.profile?.injuries || '无记录'],
  ['每周可练', () => (props.profile?.weekly_days ? props.profile.weekly_days + ' 天' : '未设置')],
]

const submit = async () => {
  await saveProfile({
    goal: form.goal || null,
    training_years: form.training_years ?? null,
    height_cm: form.height_cm ?? null,
    weight_kg: form.weight_kg ?? null,
    injuries: form.injuries || null,
    weekly_days: form.weekly_days ?? null,
  })
  dialogVisible.value = false
  emit('saved')
}
</script>

<template>
  <el-card shadow="never" class="card">
    <template #header>
      <div class="head">
        <span>🧍 用户画像（长期记忆）</span>
        <el-button size="small" text type="primary" @click="dialogVisible = true">
          编辑
        </el-button>
      </div>
    </template>

    <div v-for="[label, value] in rows" :key="label" class="row">
      <span class="label">{{ label }}</span>
      <span class="value">{{ value() }}</span>
    </div>
  </el-card>

  <el-dialog v-model="dialogVisible" title="编辑用户画像" width="480px" align-center class="profile-dialog">
    <el-form label-width="48px" class="pform">
      <div class="grid2">
        <el-form-item label="身高">
          <el-input-number v-model="form.height_cm" :min="100" :max="230" controls-position="right" />
        </el-form-item>
        <el-form-item label="体重">
          <el-input-number v-model="form.weight_kg" :min="30" :max="200" :step="0.1" controls-position="right" />
        </el-form-item>
        <el-form-item label="年限">
          <el-input-number v-model="form.training_years" :min="0" :max="50" :step="0.5" controls-position="right" />
        </el-form-item>
        <el-form-item label="每周">
          <el-input-number v-model="form.weekly_days" :min="1" :max="7" controls-position="right" />
        </el-form-item>
        <el-form-item label="目标">
          <el-select v-model="form.goal" clearable>
            <el-option value="增肌" />
            <el-option value="减脂" />
            <el-option value="保持" />
          </el-select>
        </el-form-item>
        <el-form-item label="伤病">
          <el-input v-model="form.injuries" placeholder="如：腰部旧伤" />
        </el-form-item>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.card {
  border-radius: 10px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}
.row {
  display: flex;
  font-size: 13px;
  padding: 3px 0;
}
.label {
  width: 68px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}
.value {
  word-break: break-all;
}
/* 六字段双列排布（3 行）：压缩弹窗高度；配合 align-center 垂直居中，小屏也不再出滚动条 */
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 8px;
}
:deep(.profile-dialog .el-form-item) {
  margin-bottom: 10px;
}
:deep(.profile-dialog .el-input-number),
:deep(.profile-dialog .el-select),
:deep(.profile-dialog .el-input) {
  width: 100%;
}
</style>
