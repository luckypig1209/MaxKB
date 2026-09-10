<template>
  <login-layout v-loading="bootstrapping">
    <LoginContainer :title="$t('views.login.forgotTitle')" :sub-title="$t('views.login.forgotHint')">
      <el-form
        class="login-form"
        ref="resetPasswordFormRef"
        :model="CheckEmailForm"
        :rules="rules"
        label-position="top"
      >
        <el-form-item :label="$t('views.login.loginForm.email.label')" prop="email">
          <el-input
            class="input-item"
            type="email"
            name="email"
            autocomplete="email"
            v-model="CheckEmailForm.email"
            :placeholder="$t('views.login.loginForm.email.placeholder')"
          />
        </el-form-item>
        <el-form-item :label="$t('views.login.verificationCode.label')" prop="code">
          <div class="login-captcha">
            <el-input
              class="input-item"
              name="code"
              autocomplete="one-time-code"
              v-model="CheckEmailForm.code"
              :placeholder="$t('views.login.verificationCode.placeholder')"
            />
            <el-button :disabled="isDisabled" :loading="sendLoading" @click="sendEmail">
              {{
                isDisabled
                  ? `${$t('views.login.verificationCode.resend')}（${time}s）`
                  : $t('views.login.verificationCode.getVerificationCode')
              }}
            </el-button>
          </div>
        </el-form-item>
      </el-form>
      <el-button type="primary" class="login-submit" :loading="submitting" @click="checkCode">
        {{ $t('views.login.buttons.checkCode') }}
      </el-button>
      <div class="login-card-actions">
        <router-link class="login-text-link" to="/login">{{ $t('views.login.buttons.backLogin') }}</router-link>
      </div>
    </LoginContainer>
  </login-layout>
</template>
<script setup lang="ts">
import { onBeforeMount, ref } from 'vue'
import LoginContainer from '@/layout/login-layout/LoginContainer.vue'
import LoginLayout from '@/layout/login-layout/LoginLayout.vue'
import type { CheckCodeRequest } from '@/api/type/user'
import { useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import UserApi from '@/api/user/user'
import { MsgSuccess } from '@/utils/message'
import { t } from '@/locales'
import useStore from '@/stores'

const router = useRouter()
const { user } = useStore()

const CheckEmailForm = ref<CheckCodeRequest>({
  email: '',
  code: '',
  type: 'reset_password',
})

const resetPasswordFormRef = ref<FormInstance>()
const rules = ref<FormRules<CheckCodeRequest>>({
  email: [
    {
      required: true,
      message: t('views.login.loginForm.email.requiredMessage'),
      trigger: 'blur',
    },
    {
      validator: (rule, value, callback) => {
        const emailRegExp = /^[a-zA-Z0-9_.-]+@[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)*\.[a-zA-Z0-9]{2,6}$/
        if (!emailRegExp.test(value) && value != '') {
          callback(new Error(t('views.login.loginForm.email.validatorEmail')))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
  code: [{ required: true, message: t('views.login.verificationCode.placeholder') }],
})
const bootstrapping = ref<boolean>(false)
const submitting = ref<boolean>(false)
const isDisabled = ref<boolean>(false)
const time = ref<number>(60)
const sendLoading = ref<boolean>(false)
const checkCode = () => {
  if (submitting.value) return
  submitting.value = true
  resetPasswordFormRef.value
    ?.validate()
    .then(() => UserApi.checkCode(CheckEmailForm.value, sendLoading))
    .then(() => router.push({ name: 'ResetPassword', params: CheckEmailForm.value }))
    .finally(() => {
      submitting.value = false
    })
}
const sendEmail = () => {
  resetPasswordFormRef.value?.validateField('email', (v: boolean) => {
    if (v) {
      UserApi.sendEmit(CheckEmailForm.value.email, 'reset_password', sendLoading).then(() => {
        MsgSuccess(t('views.login.verificationCode.successMessage'))
        isDisabled.value = true
        handleTimeChange()
      })
    }
  })
}
const handleTimeChange = () => {
  if (time.value <= 0) {
    isDisabled.value = false
    time.value = 60
  } else {
    setTimeout(() => {
      time.value--
      handleTimeChange()
    }, 1000)
  }
}
onBeforeMount(() => {
  bootstrapping.value = true
  user.asyncGetProfile().then(() => {
    bootstrapping.value = false
  })
})
</script>
<style lang="scss" scoped>
.login-form {
  margin-top: 24px;
}
</style>
