const TIMING_FLAG = 'bia-sso-timing'

let origin = 0
let portalProfileTiming = false

export function setPortalProfileTiming(enabled: boolean) {
  portalProfileTiming = enabled
}

export function portalProfileTimingEnabled() {
  return portalProfileTiming
}

export function markPortalStage(stage: string) {
  if (typeof performance === 'undefined' || typeof performance.now !== 'function') {
    return
  }
  const now = performance.now()
  if (stage === 'landing_ready') {
    origin = now
  }
  const elapsed = origin > 0 ? Math.round(now - origin) : 0
  try {
    performance.mark(`portal_sso_${stage}`)
  } catch {
    // Marks are diagnostic only and must never block login.
  }
  if (typeof sessionStorage === 'undefined' || sessionStorage.getItem(TIMING_FLAG) !== '1') {
    return
  }
  console.info(`portal_sso_timing stage=${stage} ms=${elapsed}`)
}
