const shanghaiFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

function parseOpportunityTime(value: string): Date | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const hasZone = /(?:Z|[+-]\d{2}:\d{2})$/.test(trimmed)
  const date = new Date(hasZone ? trimmed : `${trimmed}Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatOpportunityTime(value?: string | null): string {
  if (!value) return '-'
  const date = parseOpportunityTime(value)
  if (!date) return '-'
  const parts = shanghaiFormatter.formatToParts(date)
  const read = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? ''
  return `${read('year')}/${read('month')}/${read('day')} ${read('hour')}:${read('minute')}`
}

export function toShanghaiDayStart(value: string): string {
  return `${value}T00:00:00+08:00`
}

export function toShanghaiDayEnd(value: string): string {
  return `${value}T23:59:59.999+08:00`
}
