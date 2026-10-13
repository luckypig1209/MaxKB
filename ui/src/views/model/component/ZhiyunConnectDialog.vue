<template>
  <el-dialog
    v-model="visible"
    :title="$t('views.model.zhiyun.connect')"
    width="640px"
    append-to-body
    :close-on-click-modal="false"
    @closed="reset"
  >
    <p class="zhiyun-intro">{{ $t('views.model.zhiyun.intro') }}</p>
    <p class="zhiyun-intro">{{ $t('views.model.zhiyun.endpoint') }}</p>
    <el-form label-position="top" @submit.prevent>
      <el-form-item :label="$t('views.model.zhiyun.apiKey')" required>
        <el-input
          v-model="apiKey"
          type="password"
          show-password
          autocomplete="new-password"
          :placeholder="$t('views.model.zhiyun.apiKeyPlaceholder')"
        />
      </el-form-item>
    </el-form>
    <p v-if="errorText" class="zhiyun-error" role="alert">{{ errorText }}</p>
    <template v-if="loaded">
      <el-input
        v-model="keyword"
        clearable
        name="zhiyun_model_search"
        class="zhiyun-search"
        :placeholder="$t('views.model.zhiyun.search')"
      />
      <p class="zhiyun-summary">{{ summaryText }}</p>
    </template>
    <div v-if="hasModels" class="zhiyun-groups">
      <section v-for="group in visibleGroups" :key="group.type" class="zhiyun-group">
        <div class="zhiyun-group-title">
          <el-checkbox
            :model-value="groupChecked(group.type)"
            :indeterminate="groupPartial(group.type)"
            :disabled="choosableIds(group).length === 0"
            @change="onGroupChange(group, $event)"
          >
            {{ group.label }}（{{ group.items.length }}）
          </el-checkbox>
        </div>
        <el-checkbox-group v-model="selected" class="zhiyun-options">
          <div v-for="item in group.items" :key="item.id" class="zhiyun-option">
            <el-checkbox :value="item.id" :disabled="!canSelect(group.type, item)">
              {{ item.id }}
            </el-checkbox>
            <el-select
              v-if="group.type === 'UNKNOWN' && item.disabled_reason !== 'too_long'"
              v-model="confirmedTypes[item.id]"
              class="zhiyun-type"
              :placeholder="$t('views.model.zhiyun.chooseType')"
              @change="onUnknownType(item.id)"
            >
              <el-option
                v-for="option in typeOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <span v-else-if="item.disabled_reason" class="zhiyun-reason">
              {{ reasonText(item.disabled_reason) }}
            </span>
          </div>
        </el-checkbox-group>
      </section>
    </div>
    <p v-else-if="loaded && !loading" class="zhiyun-empty">
      {{ keyword.trim() ? $t('views.model.zhiyun.searchEmpty') : $t('views.model.zhiyun.empty') }}
    </p>
    <template #footer>
      <el-button @click="visible = false">{{ $t('common.cancel') }}</el-button>
      <el-button v-if="loaded" :loading="loading" @click="preview">{{ $t('views.model.zhiyun.refresh') }}</el-button>
      <el-button type="primary" :loading="loading" :disabled="primaryDisabled" @click="primaryAction">
        {{ loaded ? $t('views.model.zhiyun.sync') : $t('views.model.zhiyun.fetch') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import modelApi from '@/api/model/model'
import { MsgSuccess } from '@/utils/message'

const emit = defineEmits(['synced'])
const { t } = useI18n()

const GROUP_TYPES = ['LLM', 'EMBEDDING', 'RERANKER', 'UNKNOWN', 'IMAGE', 'VIDEO'] as const
type CatalogItem = { id: string; selectable?: boolean; disabled_reason?: string | null }
type CatalogGroup = { type: string; label: string; items: CatalogItem[] }

const visible = ref(false)
const loading = ref(false)
const loaded = ref(false)
const apiKey = ref('')
const keyword = ref('')
const errorText = ref('')
const summary = ref({ total: 0, selectable: 0, unknown: 0, unsupported: 0 })
const groups = ref<Record<string, CatalogItem[]>>({})
const selected = ref<string[]>([])
const confirmedTypes = ref<Record<string, string>>({})

const typeOptions = computed(() => ['LLM', 'EMBEDDING', 'RERANKER'].map((value) => ({
  value,
  label: t(`views.model.modelType.${value}`),
})))
const summaryText = computed(() => t('views.model.zhiyun.summary', summary.value))
const groupLabel = (type: string) => {
  if (type === 'UNKNOWN') return t('views.model.zhiyun.unknown')
  if (type === 'IMAGE') return t('views.model.zhiyun.image')
  if (type === 'VIDEO') return t('views.model.zhiyun.video')
  return t(`views.model.modelType.${type}`)
}
const matchesKeyword = (id: string) => id.toLowerCase().includes(keyword.value.trim().toLowerCase())
const visibleGroups = computed(() => GROUP_TYPES
  .map((type) => ({
    type,
    label: groupLabel(type),
    items: (groups.value[type] || []).filter((item) => matchesKeyword(item.id)),
  }))
  .filter((group) => group.items.length > 0))
const hasModels = computed(() => visibleGroups.value.length > 0)
const primaryDisabled = computed(() => loading.value || (loaded.value && selected.value.length === 0))

const canSelect = (type: string, item: CatalogItem) => {
  if (item.disabled_reason === 'too_long') return false
  if (item.selectable) return true
  return type === 'UNKNOWN' && Boolean(confirmedTypes.value[item.id])
}
const choosableIds = (group: CatalogGroup) => group.items.filter((item) => canSelect(group.type, item)).map((item) => item.id)
const groupChecked = (type: string) => {
  const group = visibleGroups.value.find((item) => item.type === type)
  const ids = group ? choosableIds(group) : []
  return ids.length > 0 && ids.every((id) => selected.value.includes(id))
}
const groupPartial = (type: string) => {
  const group = visibleGroups.value.find((item) => item.type === type)
  const ids = group ? choosableIds(group) : []
  const count = ids.filter((id) => selected.value.includes(id)).length
  return count > 0 && count < ids.length
}
const toggleGroup = (group: CatalogGroup, checked: boolean) => {
  const ids = new Set(selected.value)
  choosableIds(group).forEach((id) => {
    if (checked) ids.add(id)
    else ids.delete(id)
  })
  selected.value = [...ids]
}

const onGroupChange = (group: CatalogGroup, checked: unknown) => {
  toggleGroup(group, Boolean(checked))
}
const onUnknownType = (id: string) => {
  if (!confirmedTypes.value[id]) {
    selected.value = selected.value.filter((item) => item !== id)
  }
}
const reasonText = (reason: string) => t(`views.model.zhiyun.reason.${reason}`)

const reset = () => {
  loading.value = false
  loaded.value = false
  apiKey.value = ''
  keyword.value = ''
  errorText.value = ''
  summary.value = { total: 0, selectable: 0, unknown: 0, unsupported: 0 }
  groups.value = {}
  selected.value = []
  confirmedTypes.value = {}
}

const open = () => {
  reset()
  visible.value = true
}

const failureText = (error: any) => error?.message || t('views.model.zhiyun.fetchFailed')

const preview = () => {
  errorText.value = ''
  loading.value = true
  modelApi.previewZhiyun({ api_key: apiKey.value }, loading).then((res: any) => {
    const next = res?.data?.groups || {}
    groups.value = next
    summary.value = res?.data?.summary || { total: 0, selectable: 0, unknown: 0, unsupported: 0 }
    selected.value = []
    confirmedTypes.value = {}
    loaded.value = true
    if ((summary.value.total || 0) === 0) errorText.value = t('views.model.zhiyun.empty')
  }).catch((error: any) => {
    errorText.value = failureText(error)
  })
}

const sync = () => {
  errorText.value = ''
  loading.value = true
  modelApi.syncZhiyun({
    api_key: apiKey.value,
    model_ids: selected.value,
    model_types: Object.fromEntries(
      selected.value
        .filter((id) => confirmedTypes.value[id])
        .map((id) => [id, confirmedTypes.value[id]]),
    ),
  }, loading).then((res: any) => {
    const data = res?.data || {}
    MsgSuccess(t('views.model.zhiyun.syncSuccess', {
      created: (data.created || []).length,
      updated: (data.updated || []).length,
    }))
    emit('synced')
    visible.value = false
  }).catch((error: any) => {
    errorText.value = failureText(error)
  })
}

const primaryAction = () => {
  if (loaded.value) sync()
  else preview()
}

defineExpose({ open })
</script>

<style scoped>
.zhiyun-intro,
.zhiyun-empty {
  margin: 0 0 16px;
  color: var(--muted);
  line-height: 1.6;
}
.zhiyun-error {
  margin: 0 0 16px;
  padding: 8px 12px;
  color: var(--red);
  background: var(--red-s);
  border-radius: var(--el-border-radius-base);
  line-height: 1.6;
}
.zhiyun-groups {
  max-height: 360px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--el-border-radius-base);
  background: var(--surface);
}
.zhiyun-group + .zhiyun-group {
  border-top: 1px solid var(--line);
}
.zhiyun-group-title {
  padding: 8px 12px;
  background: var(--surface2);
}
.zhiyun-options {
  display: flex;
  flex-direction: column;
  padding: 8px 12px 12px;
}
.zhiyun-search,
.zhiyun-summary {
  margin: 0 0 12px;
}
.zhiyun-summary {
  color: var(--muted);
  line-height: 1.6;
}
.zhiyun-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  min-height: 28px;
  content-visibility: auto;
}
.zhiyun-option :deep(.el-checkbox) {
  flex: 1;
  height: auto;
  min-width: 0;
  margin-right: 0;
}
.zhiyun-option :deep(.el-checkbox__label) {
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 1.5;
}
.zhiyun-type {
  width: 132px;
  flex: none;
}
.zhiyun-reason {
  flex: none;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}
.zhiyun-options :deep(.el-checkbox__label) {
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
