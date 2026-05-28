# Bootstrap

Use a local checkout of the official Cypress Real World App repository.

Target base URL:

```text
http://localhost:3000/
```

Setup expectations:

- install the application with the upstream prerequisites documented in the repository README
- use Yarn Classic through Corepack, for example `corepack yarn install`
- use the upstream local development flow, which documents `corepack yarn dev` for the standard seeded local-auth stack
- verify the exact Node.js version from the upstream `.node-version` file and use Yarn Classic as documented upstream
- confirm seeded example users are available before recording tasks, for example by running `corepack yarn list:dev:users`
- keep the app self-hosted so task replay does not depend on a public deployment

Validated local runtime:

- checkout: `external/cypress-realworld-app`
- frontend: `http://localhost:3000/`
- backend: `http://localhost:3001/`
- login surface: `http://localhost:3000/signin`

Authoring focus:

- sign-in and account activity flows
- payment request or money-movement boundary tasks
- cross-view verification after a state change
