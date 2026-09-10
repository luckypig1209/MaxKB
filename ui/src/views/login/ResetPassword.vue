<template>
  <login-layout>
    <LoginContainer :title="$t('views.login.resetPassword')" :sub-title="$t('views.login.enterPassword')">
      <el-form
        class="login-form"
        ref="resetPasswordFormRef"
        :model="resetPasswordForm"
        :rules="rules"
        label-position="top"
      >
        <el-form-item :label="$t('views.login.loginForm.new_password.label')" prop="password">
          <el-input
            type="password"
            class="input-item"
            name="password"
            autocomplete="new-password"
            v-model="resetPasswordForm.password"
            :placeholder="$t('views.login.loginForm.new_password.placeholder')"
            show-password
          />
        </el-form-item>
        <el-form-item :label="$t('views.login.loginForm.re_password.label')" prop="re_password">
          <el-input
            type="password"
            class="input-item"
            name="re_password"
            autocomplete="new-password"
            v-model="resetPasswordForm.re_password"
            :placeholder="$t('views.login.loginForm.re_password.placeholder')"
            show-password
          />
        </el-form-item>
      </el-form>
      <el-button type="primary" class="login-submit" :loading="loading" @click="resetPassword">
        {{ $t('common.confirm') }}
      </el-button>
      <div class="login-card-actions">
        <router-link class="login-text-link" to="/login">{{ $t('views.login.buttons.backLogin') }}</router-link>
      </div>
    </LoginContainer>
  </login-layout>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import LoginContainer from '@/layout/login-layout/LoginContainer.vue'
import LoginLayout from '@/layout/login-layout/LoginLayout.vue'
import type { ResetPasswordRequest } from '@/api/type/user'
import { useRouter, useRoute } from 'vue-router'
import { MsgSuccess } from '@/utils/message'
import type { FormInstance, FormRules } from 'element-plus'
import UserApi from '@/api/user/user'
import { t } from '@/locales'
import JSEncrypt from 'jsencrypt'
import useStore from '@/stores'
const { user } = useStore()
const router = useRouter()
const route = useRoute()
const {
  params: { code, email },
} = route
const resetPasswordForm = ref<ResetPasswordRequest>({
  password: '',
  re_password: '',
  email: '',
  code: '',
  encrypted: false,
})

onMounted(() => {
  if (code && email) {
    resetPasswordForm.value.code = code as string
    resetPasswordForm.value.email = email as string
  } else {
    router.push('forgot_password')
  }
})

const rules = ref<FormRules<ResetPasswordRequest>>({
  password: [
    {
      required: true,
      message: t('views.login.loginForm.re_password.requiredMessage'),
      trigger: 'blur',
    },
    {
      min: 6,
      max: 20,
      message: t('views.login.loginForm.password.lengthMessage'),
      trigger: 'blur',
    },
  ],
  re_password: [
    {
      required: true,
      message: t('views.login.loginForm.re_password.requiredMessage'),
      trigger: 'blur',
    },
    {
      min: 6,
      max: 20,
      message: t('views.login.loginForm.password.lengthMessage'),
      trigger: 'blur',
    },
    {
      validator: (rule, value, callback) => {
        if (resetPasswordForm.value.password != resetPasswordForm.value.re_password) {
          callback(new Error(t('views.login.loginForm.re_password.validatorMessage')))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
})
const resetPasswordFormRef = ref<FormInstance>()
const loading = ref<boolean>(false)
const resetPassword = () => {
  resetPasswordFormRef.value
    ?.validate()
    .then(() => {
      const JSEncryptCtor = (JSEncrypt as any)?.default ? (JSEncrypt as any).default : JSEncrypt
      const js = new (JSEncryptCtor as any)()
      js.setPublicKey(user.rsaKey)
      resetPasswordForm.value.password = js.encrypt(resetPasswordForm.value.password)
      resetPasswordForm.value.re_password = js.encrypt(resetPasswordForm.value.re_password)
      resetPasswordForm.value.encrypted = true
      return UserApi.postResetPassword(resetPasswordForm.value, loading)
    })
    .then(() => {
      MsgSuccess(t('common.modifySuccess'))
      router.push({ name: 'login' })
    })
}
</script>
<style lang="scss" scoped>
.login-form {
  margin-top: 24px;
}
</style>
