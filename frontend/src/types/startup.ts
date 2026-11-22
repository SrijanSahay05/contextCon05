export type Folder = 'discover' | 'watching' | 'outreach' | 'discarded'

export type Momentum = 'high' | 'steady' | 'slow'

export type OutreachStatus = 'Drafting intro' | 'Awaiting reply' | 'Meeting booked'

export interface NewsItem {
  date: string
  title: string
  source: string
  url?: string | null
}

export interface FundingEvent {
  date: string
  kind: 'round' | 'grant'
  name: string
  amount: string
  detail: string
}

export interface Hire {
  date: string
  person: string
  role: string
  from: string
}

/** Each part is 0–100, or null when the data to judge it is missing. */
export interface ScoreBreakdown {
  thesis: number | null
  momentum: number | null
  hiring: number | null
  timing: number | null
}

/** What a search returns for each startup. */
export interface StartupSummary {
  id: string
  source: 'sample' | 'crustdata'
  crustdataId?: number
  name: string
  tagline: string
  sector: string
  stage: string
  city: string
  founded: number | null
  domain?: string | null
  profileUrl?: string | null
  /** Overall fit, 0–100. */
  score: number
  breakdown: ScoreBreakdown
  signals: string[]
  why: string
  /** Short line about the team, e.g. "24 people · Fintech". */
  teamLine: string
  momentum: Momentum
  /** Days until the backend re-checks this company, set from its history. */
  cadenceDays: number
  hue: number
}

/** The deeper record behind the overlay and the full page, fetched on demand. */
export interface StartupDetail {
  headcount: { now: number | null; sixMonthsAgo: number | null }
  news: NewsItem[]
  /** False when news was matched by name only and may include namesakes. */
  newsVerified: boolean
  funding: FundingEvent[]
  hires: Hire[]
  openRoles: string[]
}

export interface Item extends StartupSummary {
  folder: Folder
  /** Where a discarded startup came from, so Restore can put it back. */
  previousFolder?: Folder
  outreach?: { status: OutreachStatus; nextStep: string }
  detail?: StartupDetail
}

export interface SearchPlan {
  query: string
  country: string | null
  foundedAfter: number | null
  minHeadcount: number | null
  maxHeadcount: number | null
  planner: 'claude' | 'rules'
}

export interface SearchResponse {
  plan: SearchPlan
  startups: Omit<StartupSummary, 'source'>[]
  creditsUsed: number
}

/** The state of the latest thesis search, shown under the composer. */
export type SearchStatus =
  | { state: 'busy'; thesis: string }
  | { state: 'done'; thesis: string; plan: SearchPlan; count: number; credits: number }
  | { state: 'error'; thesis: string; message: string }
