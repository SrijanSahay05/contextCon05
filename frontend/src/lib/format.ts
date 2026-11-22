const dateFmt = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

export const formatDate = (iso: string) => dateFmt.format(new Date(`${iso}T00:00:00`))

export const growthPct = (now: number, before: number) => (before > 0 ? Math.round(((now - before) / before) * 100) : 0)

export const cadenceLabel = (days: number) => (days === 1 ? 'Re-checks tomorrow' : `Re-checks in ${days} days`)
