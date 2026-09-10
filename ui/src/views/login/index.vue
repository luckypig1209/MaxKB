<template>
  <login-layout v-loading="bootstrapping">
    <LoginContainer
      :title="cardTitle"
      :sub-title="cardSubtitle"
      :show-security-note="!showQrCodeTab"
    >
      <el-form
        v-if="!showQrCodeTab"
        class="login-form"
        :rules="rules"
        :model="loginForm"
        ref="loginFormRef"
        label-position="top"
        @keyup.enter="loginHandle"
      >
        <el-form-item :label="$t('views.login.loginForm.username.label')" prop="username">
          <el-input
            class="input-item"
            name="username"
            autocomplete="username"
            spellcheck="false"
            v-model="loginForm.username"
            @blur="handleUsernameBlur(loginForm.username)"
            :placeholder="$t('views.login.loginForm.username.placeholder')"
          />
        </el-form-item>
        <el-form-item :label="$t('views.login.loginForm.password.label')" prop="password">
          <el-input
            class="input-item"
            name="password"
            autocomplete="current-password"
            :type="passwordVisible ? 'text' : 'password'"
            v-model="loginForm.password"
            :placeholder="$t('views.login.loginForm.password.placeholder')"
          >
            <template #suffix>
              <button
                type="button"
                class="login-eye"
                :aria-label="passwordVisible ? $t('views.login.hidePassword') : $t('views.login.showPassword')"
                @click="passwordVisible = !passwordVisible"
              >
                <el-icon><View v-if="passwordVisible" /><Hide v-else /></el-icon>
              </button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item
          v-if="loginMode !== 'LDAP' && identifyCode"
          :label="$t('views.login.loginForm.captcha.label')"
          prop="captcha"
        >
          <div class="login-captcha">
            <el-input
              class="input-item"
              name="captcha"
              autocomplete="off"
              v-model="loginForm.captcha"
              :placeholder="$t('views.login.loginForm.captcha.placeholder')"
            />
            <button
              type="button"
              class="login-captcha__refresh"
              :aria-label="$t('views.login.refreshCaptcha')"
              :disabled="captchaRefreshing"
              @click="makeCode(loginForm.username)"
            >
              <img :src="identifyCode" :alt="$t('views.login.captchaImageAlt')" />
            </button>
          </div>
          <p class="login-captcha__hint">{{ $t('views.login.captchaHint') }}</p>
        </el-form-item>
      </el-form>

      <el-button
        v-if="!showQrCodeTab"
        type="primary"
        class="login-submit"
        :loading="submitting"
        @click="loginHandle"
      >
        {{ submitting ? $t('views.login.buttons.loggingIn') : $t('views.login.buttons.login') }}
      </el-button>
      <div v-if="!showQrCodeTab" class="login-card-actions">
        <router-link class="login-text-link" to="/forgot_password">
          {{ $t('views.login.forgotPassword') }}？
        </router-link>
      </div>

      <div v-if="showQrCodeTab">
        <QrCodeTab :tabs="orgOptions" :default-tab="defaultQrTab" />
        <div class="login-card-actions">
          <button type="button" class="login-text-link login-eye" @click="changeMode('')">
            {{ $t('views.login.backToAccount') }}
          </button>
        </div>
      </div>

      <div class="login-methods" v-if="modeList.length > 1">
        <p class="login-methods__label">{{ $t('views.login.moreMethod') }}</p>
        <div class="login-methods__list">
          <template v-for="item in modeList" :key="item || 'local'">
            <el-tooltip
              v-if="item !== '' && loginMode !== item && item !== 'QR_CODE'"
              :content="methodLabel(item)"
            >
              <button
                type="button"
                class="login-method"
                :aria-label="methodLabel(item)"
                @click="changeMode(item)"
              >
                {{ methodShort(item) }}
              </button>
            </el-tooltip>
            <el-tooltip
              v-if="item === 'QR_CODE' && loginMode !== item"
              :content="$t('views.login.scanLogin')"
            >
              <button
                type="button"
                class="login-method"
                :aria-label="$t('views.login.scanLogin')"
                @click="changeMode('QR_CODE')"
              >
                <img src="@/assets/icon_qr_outlined.svg" width="18" height="18" alt="" />
              </button>
            </el-tooltip>
            <el-tooltip
              v-if="item === '' && loginMode !== ''"
              :content="$t('views.login.backToAccount')"
            >
              <button
                type="button"
                class="login-method"
                :class="{ 'is-on': loginMode === '' }"
                :aria-label="$t('views.login.backToAccount')"
                @click="changeMode('')"
              >
                <el-icon><UserFilled /></el-icon>
              </button>
            </el-tooltip>
          </template>
        </div>
      </div>
    </LoginContainer>
  </login-layout>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeMount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { Hide, UserFilled, View } from '@element-plus/icons-vue'
import type { LoginRequest } from '@/api/type/login'
import LoginContainer from '@/layout/login-layout/LoginContainer.vue'
import LoginLayout from '@/layout/login-layout/LoginLayout.vue'
import loginApi from '@/api/user/login'
import authApi from '@/api/system-settings/auth-setting'
import { getBrowserLang, t } from '@/locales'
import useStore from '@/stores'
import { useI18n } from 'vue-i18n'
import QrCodeTab from '@/views/login/scanCompinents/QrCodeTab.vue'
import { MsgConfirm, MsgError } from '@/utils/message.ts'
import * as dd from 'dingtalk-jsapi'
import { loadScript } from '@/utils/common'
import JSEncrypt from 'jsencrypt'

const router = useRouter()
const { login, user } = useStore()
const { locale } = useI18n({ useScope: 'global' })
const bootstrapping = ref<boolean>(false)
const submitting = ref<boolean>(false)
const loading = ref<boolean>(false)
const passwordVisible = ref(false)
const captchaRefreshing = ref(false)
const route = useRoute()
const identifyCode = ref<string>('')
const loginFormRef = ref<FormInstance>()
const authSetting = ref<any>(null)
const defaultQrTab = ref<string>('')
const loginForm = ref<LoginRequest>({
  username: '',
  password: '',
  captcha: '',
})

const rules = ref<FormRules<LoginRequest>>({
  username: [
    {
      required: true,
      message: t('views.login.loginForm.username.requiredMessage'),
      trigger: 'blur',
    },
  ],
  password: [
    {
      required: true,
      message: t('views.login.loginForm.password.requiredMessage'),
      trigger: 'blur',
    },
  ],
  captcha: [
    {
      required: false,
      message: t('views.login.loginForm.captcha.requiredMessage'),
      trigger: 'blur',
    },
  ],
})

const loginHandle = () => {
  if (!loginFormRef.value || submitting.value) {
    return
  }
  loginFormRef.value.validate((valid) => {
    if (!valid) {
      nextTick(() => {
        const first = document.querySelector('.login-form .el-form-item.is-error input') as HTMLInputElement | null
        first?.focus()
      })
      return
    }
    submitting.value = true
    if (loginMode.value === 'LDAP') {
      login
        .asyncLdapLogin(loginForm.value)
        .then(() => {
          locale.value = localStorage.getItem('MaxKB-locale') || getBrowserLang() || 'en-US'
          router.push({ name: 'home' })
        })
        .catch(() => {
          submitting.value = false
        })
    } else {
      const JSEncryptCtor = (JSEncrypt as any)?.default ? (JSEncrypt as any).default : JSEncrypt
      const js = new (JSEncryptCtor as any)()
      js.setPublicKey(user.rsaKey)
      const jsonData = JSON.stringify(loginForm.value)
      const encryptedBase64 = js.encrypt(jsonData)

      login
        .asyncLogin({ encryptedData: encryptedBase64, username: loginForm.value.username })
        .then(() => {
          locale.value = localStorage.getItem('MaxKB-locale') || getBrowserLang() || 'en-US'
          localStorage.setItem('workspace_id', 'default')
          router.push({ name: 'home' })
        })
        .catch(() => {
          const username = loginForm.value.username
          submitting.value = false
          makeCode(username)
        })
    }
  })
}

function makeCode(username?: string) {
  captchaRefreshing.value = true
  loginApi
    .getCaptcha(username)
    .then((res: any) => {
      if (res && res.data && res.data.captcha) {
        identifyCode.value = res.data.captcha
      }
    })
    .catch((error) => {
      console.error('Failed to get captcha:', error)
    })
    .finally(() => {
      captchaRefreshing.value = false
    })
}

function handleUsernameBlur(username: string) {
  makeCode(username)
}

onBeforeMount(() => {
  bootstrapping.value = true
  user.asyncGetProfile().then((res) => {
    // 企业版和专业版：第三方登录
    if (user.isPE() || user.isEE()) {
      authApi.getLoginAuthSetting().then((res) => {
        if (Object.keys(res.data).length > 0) {
          authSetting.value = res.data
        } else {
          authSetting.value = {
            max_attempts: 1,
            default_value: 'LOCAL',
          }
        }
        const params = route.query
        if (params.login_mode !== 'manual') {
          if (authSetting.value?.login_methods) {
            modeList.value = authSetting.value?.login_methods
            if (modeList.value.includes('LOCAL')) {
              modeList.value = ['LOCAL', ...modeList.value.filter((item) => item !== 'LOCAL')]
            } else if (modeList.value.includes('LDAP')) {
              modeList.value = ['LDAP', ...modeList.value.filter((item) => item !== 'LDAP')]
            }
            loginMode.value = modeList.value[0] || 'LOCAL'
            if (!modeList.value.includes('LOCAL') && !modeList.value.includes('LDAP')) {
              loginMode.value = ''
            }
            if (
              modeList.value.length == 1 &&
              ['CAS', 'OIDC', 'OAuth2', 'SAML2'].includes(modeList.value[0])
            ) {
              redirectAuth(modeList.value[0])
            }
            // 这里的modeList 是oauth2 cas ldap oidc 这四个 还会有 lark wecom dingtalk
            // 获取到的 modeList中除'CAS', 'OIDC', 'OAuth2' LOCAL之外的登录方式
            QrList.value = modeList.value.filter(
              (item) => !['CAS', 'OIDC', 'OAuth2', 'LOCAL', 'LDAP', 'SAML2'].includes(item),
            )
            // modeList需要去掉lark wecom dingtalk
            modeList.value = modeList.value.filter(
              (item) => !['lark', 'wecom', 'dingtalk'].includes(item),
            )
            if (QrList.value.length > 0) {
              QrList.value.forEach((item) => {
                orgOptions.value.push({
                  key: item,
                  value:
                    item === 'wecom'
                      ? t('views.system.authentication.scanTheQRCode.wecom')
                      : item === 'dingtalk'
                        ? t('views.system.authentication.scanTheQRCode.dingtalk')
                        : t('views.system.authentication.scanTheQRCode.lark'),
                })
              })
              if (!modeList.value.includes('LOCAL') && !modeList.value.includes('LDAP')) {
                showQrCodeTab.value = true
              }
              modeList.value = ['QR_CODE', ...modeList.value]
            }
          }
          // 如果modeList 只包含了LOCAL 就可以置空
          if (modeList.value.length === 1 && modeList.value[0] === 'LOCAL') {
            modeList.value = []
          }
          const defaultMode = authSetting.value.default_value
          if (['lark', 'wecom', 'dingtalk'].includes(defaultMode)) {
            changeMode('QR_CODE', false)
            defaultQrTab.value = defaultMode
          } else {
            changeMode(defaultMode, false)
          }
        }
      })
    } else {
      authSetting.value = {
        max_attempts: 1,
        default_value: 'LOCAL',
      }
    }
    bootstrapping.value = false
  })
})

const modeList = ref<string[]>([''])
const QrList = ref<any[]>([''])
const loginMode = ref('')
const showQrCodeTab = ref(false)

interface qrOption {
  key: string
  value: string
}

const orgOptions = ref<qrOption[]>([])

function uuidv4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

const cardTitle = computed(() =>
  showQrCodeTab.value ? t('views.login.scanLogin') : t('views.login.welcome'),
)
const cardSubtitle = computed(() => {
  if (showQrCodeTab.value) return t('views.login.scanHint')
  if (loginMode.value === 'LDAP') return t('views.login.ldapHint')
  return t('views.login.welcomeHint')
})

function methodLabel(item: string) {
  const map: Record<string, string> = {
    LDAP: t('views.login.methods.ldap'),
    CAS: t('views.login.methods.cas'),
    OIDC: t('views.login.methods.oidc'),
    OAuth2: t('views.login.methods.oauth2'),
    SAML2: t('views.login.methods.saml2'),
    LOCAL: t('views.login.backToAccount'),
  }
  return map[item] || item
}

function methodShort(item: string) {
  if (item === 'OAuth2') return 'O2'
  if (item === 'SAML2') return 'S2'
  return item.slice(0, 2)
}

function redirectAuth(authType: string, needMessage: boolean = true) {
  if (authType === 'LDAP' || authType === '' || authType === 'LOCAL') {
    return
  }
  authApi.getLoginViewAuthSetting(authType, loading).then((res: any) => {
    if (!res.data || !res.data.config) {
      return
    }

    const config = res.data.config
    // 构造带查询参数的redirectUrl
    const redirectUrl = `${config.redirectUrl}`
    let url
    if (authType === 'CAS') {
      url = config.ldpUri
      url +=
        url.indexOf('?') !== -1
          ? `&service=${encodeURIComponent(redirectUrl)}`
          : `?service=${encodeURIComponent(redirectUrl)}`
    } else if (authType === 'OIDC') {
      const scope = config.scope || 'openid+profile+email'
      url = `${config.authEndpoint}?client_id=${config.clientId}&redirect_uri=${redirectUrl}&response_type=code&scope=${scope}`
      if (config.state) {
        url += `&state=${config.state}`
      }
    } else if (authType === 'OAuth2') {
      url = `${config.authEndpoint}?client_id=${config.clientId}&response_type=code&redirect_uri=${redirectUrl}&state=${uuidv4()}`
      if (config.scope) {
        url += `&scope=${config.scope}`
      }
    } else if (authType === 'SAML2') {
      loginApi.samlLogin().then((res: any) => {
        window.location.href = res.data
      })
    }
    if (!url) {
      return
    }
    if (needMessage) {
      MsgConfirm(t('views.login.jump_tip'), '', {
        confirmButtonText: t('views.login.jump'),
        cancelButtonText: t('common.cancel'),
        confirmButtonClass: '',
      })
        .then(() => {
          window.location.href = url
        })
        .catch(() => {})
    } else {
      console.log('url', url)
      window.location.href = url
    }
  })
}

function changeMode(val: string, needMessage: boolean = true) {
  loginMode.value = val === 'LDAP' ? val : ''
  if (val === 'QR_CODE') {
    loginMode.value = val
    showQrCodeTab.value = true
    return
  }
  showQrCodeTab.value = false
  loginForm.value = {
    username: '',
    password: '',
    captcha: '',
  }
  redirectAuth(val, needMessage)
  loginFormRef.value?.clearValidate()
}


declare const window: any

onMounted(() => {
  const route = useRoute()
  const currentUrl = ref(route.fullPath)
  const params = new URLSearchParams(currentUrl.value.split('?')[1])
  const client = params.get('client')

  const handleDingTalk = () => {
    const code = params.get('corpId')
    if (code) {
      dd.runtime.permission.requestAuthCode({ corpId: code }).then((res) => {
        console.log('DingTalk client request success:', res)
        login.dingOauth2Callback(res.code).then(() => {
          router.push({ name: 'home' })
        })
      })
    }
  }

  const handleLark = () => {
    const appId = params.get('appId')
    const callRequestAuthCode = () => {
      window.tt?.requestAuthCode({
        appId: appId,
        success: (res: any) => {
          login.larkCallback(res.code).then(() => {
            router.push({ name: 'home' })
          })
        },
        fail: (error: any) => {
          MsgError(error)
        },
      })
    }

    loadScript('https://lf-scm-cn.feishucdn.com/lark/op/h5-js-sdk-1.5.35.js', {
      jsId: 'lark-sdk',
      forceReload: true,
    })
      .then(() => {
        if (window.tt) {
          window.tt.requestAccess({
            appID: appId,
            scopeList: [],
            success: (res: any) => {
              login.larkCallback(res.code).then(() => {
                router.push({ name: 'home' })
              })
            },
            fail: (error: any) => {
              const { errno } = error
              if (errno === 103) {
                callRequestAuthCode()
              }
            },
          })
        } else {
          callRequestAuthCode()
        }
      })
      .catch((error) => {
        console.error('SDK 加载失败:', error)
      })
  }

  switch (client) {
    case 'dingtalk':
      handleDingTalk()
      break
    case 'lark':
      handleLark()
      break
    default:
      break
  }
})
</script>
<style lang="scss" scoped>
.login-form {
  margin-top: 24px;
}
</style>
