<template>
  <login-layout>
    <LoginContainer
      :title="$t('views.login.portalSso.title')"
      :sub-title="$t('views.login.portalSso.subtitle')"
      :show-security-note="false"
    >
      <div class="portal-sso-state" aria-live="polite">
        <el-icon v-if="status === 'loading'" class="portal-sso-state__loading is-loading">
          <Loading />
        </el-icon>
        <p class="portal-sso-state__message">{{ statusMessage }}</p>

        <div v-if="status !== 'loading'" class="portal-sso-state__actions">
          <el-button type="primary" @click="returnToPortal">
            {{ $t('views.login.portalSso.returnToPortal') }}
          </el-button>
          <el-button plain @click="useLocalLogin">
            {{ $t('views.login.portalSso.useLocalLogin') }}
          </el-button>
        </div>
      </div>
    </LoginContainer>
  </login-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import LoginContainer from '@/layout/login-layout/LoginContainer.vue'
import LoginLayout from '@/layout/login-layout/LoginLayout.vue'
import useStore from '@/stores'
import {
  claimPortalTicketAttempt,
  readPortalTicket,
  sanitizePortalTarget,
} from '@/views/login/portal-sso'

type PortalSsoStatus = 'loading' | 'ticket' | 'config' | 'unbound' | 'unavailable'

const router = useRouter()
const route = useRoute()
const { login } = useStore()
const { locale, t } = useI18n({ useScope: 'global' })
const status = ref<PortalSsoStatus>('loading')

const statusMessage = computed(() => {
  const key = {
    loading: 'views.login.portalSso.loading',
    ticket: 'views.login.portalSso.ticketInvalid',
    config: 'views.login.portalSso.configError',
    unbound: 'views.login.portalSso.accountUnbound',
    unavailable: 'views.login.portalSso.unavailable',
  }[status.value]
  return t(key)
})

function scrubLandingUrl() {
  const url = new URL(window.location.href)
  const ticketHash = url.hash
  url.hash = ''
  // Also scrub the retired management ?token= convention when a stale link
  // combines it with a portal fragment.
  url.searchParams.delete('token')
  const cleanUrl = `${url.pathname}${url.search}${url.hash}` || '/'
  window.history.replaceState(window.history.state, document.title, cleanUrl)
  return ticketHash
}

function errorCode(error: any): string | number | undefined {
  const payload = error?.response?.data || error?.data || error
  return payload?.code || payload?.error?.code || error?.response?.status
}

function setFailure(error: unknown) {
  const code = errorCode(error)
  if (code === 'SSO_CONFIG_INVALID' || code === 'SSO_DISABLED') {
    status.value = 'config'
  } else if (code === 'SSO_BIND_REQUIRED' || code === 'SSO_USER_DISABLED') {
    status.value = 'unbound'
  } else if (
    code === 'SSO_TICKET_INVALID' ||
    code === 'SSO_INVALID_REQUEST' ||
    code === 'SSO_TIMESTAMP_INVALID' ||
    code === 'SSO_NONCE_REPLAY'
  ) {
    status.value = 'ticket'
  } else {
    status.value = 'unavailable'
  }
}

async function consumeTicket() {
  // The fragment is captured before replacement, and the replacement happens
  // before any network request or store action can run.
  const hash = scrubLandingUrl()
  const ticket = readPortalTicket(hash)
  if (!ticket || !(await claimPortalTicketAttempt(ticket))) {
    status.value = 'ticket'
    return
  }

  try {
    // Match the established local-login success path: initialize the default
    // workspace, issue a normal session through the login store, then load the
    // profile before entering the protected router.
    localStorage.setItem('workspace_id', 'default')
    const session = await login.asyncPortalSsoLogin(ticket)
    locale.value = localStorage.getItem('MaxKB-locale') || locale.value
    await router.replace(sanitizePortalTarget(session?.target))
  } catch (error) {
    setFailure(error)
  }
}

function useLocalLogin() {
  router.replace({ name: 'login', query: { login_mode: 'manual' } })
}

function returnToPortal() {
  // The portal URL is intentionally not reconstructed from ticket data and
  // arbitrary referrers are not trusted as navigation destinations.
  if (window.history.length > 1) {
    window.history.back()
  } else {
    useLocalLogin()
  }
}

onMounted(() => {
  // Keep route access explicit so a direct component mount cannot bypass the
  // router's public-route handling in tests or embedded shells.
  if (route.name !== 'PortalSso') {
    router.replace({ name: 'PortalSso' })
    return
  }
  void consumeTicket()
})
</script>

<style scoped lang="scss">
.portal-sso-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  min-height: 180px;
  justify-content: center;
  text-align: center;
}

.portal-sso-state__loading {
  color: var(--accent-ink);
  font-size: 28px;
}

.portal-sso-state__message {
  margin: 0;
  color: var(--ink2);
  line-height: 1.6;
}

.portal-sso-state__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}
</style>
