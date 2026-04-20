select
  u.listing_pk,
  l.source,
  l.title,
  u.route,
  u.ev,
  u.ev_lower,
  u.action_score,
  u.scored_at
from underwriting_scores u
join listings l on l.listing_pk = u.listing_pk
where u.route <> 'IGNORE'
order by u.scored_at desc;
