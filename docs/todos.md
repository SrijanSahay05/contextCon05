# TODOs

## Switch external refresh from hourly polling to Crustdata Watchers

**Now:** a scheduled job (roughly hourly) re-runs the indexed searches
(`social_post/search`, `job/search`, `web/search`, `company/enrich`) with a
"newer than last seen" cutoff (e.g. `date_posted > last_seen`) and writes new
results into memory.

**Why not Watchers yet:** Crustdata Watchers don't give live updates. The
default refresh window is 30 days (`refresh_frequency_days`); a 1-day refresh
costs 150 credits per changed entity, which is too much for our credit budget.

**Later:** move the slow-moving feeds to Watchers on the default 30-day refresh
(webhook delivery):

- Company Entity Watcher (`/watch/company`): 5 credits per changed company.
  Covers competitors' headcount, funding and news.
- Social Post Watcher (`/watch/social_post/search`): 2 credits per new post.
  Covers posts from the influencers and keywords we follow.
- Person Entity Watcher (`/watch/person`) and Job Watcher (`/watch/job/search`),
  as needed.

Use the 30-day snapshots to analyse how sentiment changed over the last month
(per competitor, influencer and topic), rather than only showing the latest
posts.

Refs: https://docs.crustdata.com/general/pricing.md,
https://docs.crustdata.com/watcher-docs/social-post/discovery.md,
https://docs.crustdata.com/watcher-docs/company/entity.md

## Automate grant form submission

**Now:** we rebuild each grant's form as a document, answer every question
from internal + external context, and founders copy-paste the reviewed
answers into the portal by hand.

**Later:** fill and submit the portal form automatically (browser
automation), only after a founder approves, and exactly once per grant.
Not now: portals need logins and CAPTCHAs, there's no safe way to test
submitting live, and a submission can't be taken back.
