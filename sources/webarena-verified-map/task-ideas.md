# Task Ideas

Planned first batch:

1. `webarena-map-open-directions-001` recorded
2. `webarena-map-open-layers-panel-001` recorded
3. `webarena-map-open-share-panel-001` recorded
4. `webarena-map-reverse-monaco-route-001` recorded
5. `webarena-map-switch-monaco-route-to-bike-001` recorded
6. `webarena-map-switch-monaco-route-to-foot-001` recorded
7. `webarena-map-search-cmu-from-home-001` recorded
8. `webarena-map-search-schenley-plaza-from-home-001` recorded
9. `webarena-map-reverse-monaco-route-to-bike-001` recorded
10. `webarena-map-reverse-monaco-route-to-foot-001` recorded
11. `webarena-map-reverse-monaco-route-to-bike-share-001` recorded
12. `webarena-map-open-more-union-square-results-001` candidate
13. `webarena-map-long-route-disambiguation-001` blocked until a richer second search state than the current broken relation pages is available

Authoring rules:
- keep this source non-mutating by default
- prioritize search, disambiguation, and route-planning tasks
- survey is complete and candidate sets are usable on the seeded Monaco route surface plus the two stable geocoder-backed search result pages
- use `./scripts/setup_webarena_map_data.sh ... routing` plus `./scripts/check_webarena_map_readiness.sh ... routing` as the gate before route-only work
- use `./scripts/setup_webarena_map_data.sh ... geocoder` plus `./scripts/check_webarena_map_readiness.sh ... search` as the gate before search/disambiguation work
- the first route tasks should stay on the seeded coordinate-driven Monaco surface
- the next reliable route tasks can safely compose reverse, engine-switch, and share-panel states on that seeded Monaco surface
- the first search tasks should stay on stable home-search or result-list states; current relation detail pages reached from result links are not benchmark-quality yet because they resolve to `Not Found`
