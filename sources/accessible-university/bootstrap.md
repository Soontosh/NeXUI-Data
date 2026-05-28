# Bootstrap

Accessible University is a public live demo and does not require local application setup.

## Base URL

`https://projects.accesscomputing.uw.edu/au/`

## Relevant Public Pages

- Overview: `https://projects.accesscomputing.uw.edu/au/`
- Before: `https://projects.accesscomputing.uw.edu/au/before.html`
- After: `https://projects.accesscomputing.uw.edu/au/after.html`
- Info: `https://projects.accesscomputing.uw.edu/au/info.html`

## Optional Upstream Reference

The overview page links to a public GitHub repository for the source:

- `https://github.com/terrill/AU`

## Commands

```bash
./nexui validate-source sources/accessible-university --check-remote
./nexui survey-source sources/accessible-university --overwrite
```

## Notes

- No authentication bootstrap is required.
- No seeded accounts or runtime reset steps are needed.
- If the public site changes materially, compare it with the upstream GitHub repository before recording new tasks.
