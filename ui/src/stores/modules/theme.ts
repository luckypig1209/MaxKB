import { defineStore } from 'pinia'
import { cloneDeep } from 'lodash'
import { useElementPlusTheme } from 'use-element-plus-theme'
import ThemeApi from '@/api/system-settings/theme'
import type {Ref} from "vue";
export interface themeStateTypes {
  themeInfo: any
}
const MAXKB_BLUE = '#3370FF'
const defalueColor = '#6c5ce7'

function resolveProductTheme(color?: string) {
  if (!color || color.toUpperCase() === MAXKB_BLUE) return defalueColor
  return color
}

const useThemeStore = defineStore('theme', {
  state: (): themeStateTypes => ({
    themeInfo: null,
  }),
  actions: {
    isDefaultTheme() {
      const theme = this.themeInfo?.theme
      return !theme || resolveProductTheme(theme) === defalueColor
    },

    setTheme(data?: any) {
      const next = resolveProductTheme(data?.theme || this.themeInfo?.theme)
      const { changeTheme } = useElementPlusTheme(resolveProductTheme(this.themeInfo?.theme))
      changeTheme(next)
      this.themeInfo = cloneDeep(data)
    },

    async theme(loading?: Ref<boolean>) {
      return await ThemeApi.getThemeInfo(loading).then((ok) => {
        this.setTheme(ok.data)
      })
    },
  },
})

export default useThemeStore
