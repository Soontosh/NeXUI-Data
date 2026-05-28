# Reset Notes

This track should always be treated as reseedable.

Reset requirements:

- restore the seeded database state before recording new tasks
- clear any user-generated payments, requests, or notifications created by prior runs
- prefer the upstream seeded local development flow, which reseeds the local JSON database on start
- if authoring requires a known fresh dataset, run `corepack yarn db:seed:dev` before starting the app again
- the validated local runtime also reseeds automatically on `corepack yarn dev`

Do not record tasks against a dirty local database.
