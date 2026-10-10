interface LoginRequest {
  /**
   * 用户名
   */
  username: string
  /**
   * 密码
   */
  password: string
  /**
   * 验证码
   */
  captcha: string
  /**
   * 加密数据
   */
  encryptedData?: string
}

interface PortalSsoExchangeRequest {
  ticket: string
}

interface PortalSsoExchangeResponse {
  token: string
  target?: string
}

export type { LoginRequest, PortalSsoExchangeRequest, PortalSsoExchangeResponse }
