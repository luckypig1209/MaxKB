import { t } from '@/locales'

export const themeList = [
  {
    label: t('theme.default'),
    value: '#3370FF',
    loginBackground: 'hongxin',
  },
  {
    label: t('theme.orange'),
    value: '#FF8800',
    loginBackground: 'hongxin',
  },
  {
    label: t('theme.green'),
    value: '#00B69D',
    loginBackground: 'hongxin',
  },
  {
    label: t('theme.purple'),
    value: '#7F3BF5',
    loginBackground: 'hongxin',
  },
  {
    label: t('theme.red'),
    value: '#F01D94',
    loginBackground: 'hongxin',
  },
]

export function getThemeImg(val: string) {
  if (!val) return 'hongxin'
  return themeList.filter((v) => v.value === val)?.[0]?.loginBackground || 'hongxin'
}

export const defaultSetting = {
  icon: '',
  loginLogo: '',
  loginImage: '',
  title: '商机智能分析系统',
  slogan: t('theme.defaultSlogan'),
}

export const defaultPlatformSetting = {
  showUserManual: false,
  userManualUrl: t('layout.userManualUrl'),
  showForum: false,
  forumUrl: t('layout.forumUrl'),
  showProject: false,
  projectUrl: 'https://github.com/1Panel-dev/MaxKB',
}

export function hexToRgba(hex?: string, alpha?: number) {
  // 将16进制颜色值的两个字符一起转换成十进制
  if (!hex) {
    return ''
  } else {
    const r = parseInt(hex.slice(1, 3), 16)
    const g = parseInt(hex.slice(3, 5), 16)
    const b = parseInt(hex.slice(5, 7), 16)

    // 返回RGBA格式的字符串
    return `rgba(${r}, ${g}, ${b}, ${alpha})`
  }
}
