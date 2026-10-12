export type AvatarAccount = {
  source?: string
  nick_name?: string
  username?: string
}

export type AvatarAccountLabel = {
  portal: boolean
  primary: string
  title: string
  showUsername: boolean
  username: string
}

export function avatarAccountLabel(account: AvatarAccount | null | undefined): AvatarAccountLabel {
  const nick = (account?.nick_name || '').trim()
  const username = account?.username || ''
  const portal = account?.source === 'PORTAL'
  return {
    portal,
    primary: nick,
    title: nick,
    showUsername: !portal && username.length > 0,
    username: portal ? '' : username,
  }
}
